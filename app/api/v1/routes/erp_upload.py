"""商品图片上传 / 读取 —— 把 `products.image_url` 这个字段真正接通。

## 背景

`products.image_url`（String(255)）后端一直就有，`ProductCreate` / `ProductUpdate` /
`ProductRead` 三个 schema 也都带着它。但前端此前只有一个手填的「图片链接」文本框，
而且**全前端没有任何地方渲染它** —— 等于一个死字段。这一步补上落盘链路，
让「选本地图片 → 看到预览 → 存进商品档案」成立。

## 为什么复用 `app/core/file_storage.py` 而不是自己写落盘

那个模块是项目里唯一处理「用户上传的二进制要留下来」的地方，三件最容易出错的事
已经在那里有唯一实现：

  · **存到哪**：未打包写项目根 `data/`，打包后写 **exe 同目录**的 `data/`。
    绝不能写进代码目录 —— PyInstaller 的 `_MEIPASS` 是**只读**解包目录，写必失败。
  · **存什么名**：uuid 前缀 + 净化后的原名，避免碰撞/覆盖，也避免用户文件名里的
    路径分隔符与控制字符落到磁盘上。
  · **读什么路径**：`absolute_path()` 把 `../` 这类越界访问挡在库外。

这里只做它没做的两件事：**图片专属的校验**（文件头嗅探 + 上限）与 **HTTP 层**。

## 两个接口，鉴权刻意不对称

    POST /api/v1/upload/product-image       需要登录（要写磁盘，不能匿名）
    GET  /api/v1/uploads/products/{文件名}   **公开**

读取接口必须公开：它的唯一用途是喂给 `<img src="...">`，而浏览器加载 `<img>` 时
**不会带 `Authorization` 头**，加任何鉴权都会让图片直接裂掉。可接受的理由：文件名带
12 位随机 uuid 前缀，不可枚举；内容也仅仅是商品照片。（本机桌面部署，前端 dist
本身就是公开托管的，安全边界没有额外变化。）

## 为什么 URL 挂在 `/api/v1` 下，而不是新开一个 `/uploads` 挂载点

1. 开发模式下前端走 vite 的 `/api` 代理，挂在 `/api` 下面**开发时也能看到图**；
   另起 `/uploads` 就得再配一条代理。
2. `app/main.py` 末尾的 `mount("/", ...)` 会吞掉所有路径 —— 新挂载点必须插在它
   **之前**，顺序一错就是"路由明明在、访问却 404"。用一个显式路由没有这个陷阱。
3. `frontend/public/sw.js` 对 `/api/` 开头的请求**直接 return**（不接管、不缓存），
   于是图片的缓存行为完全由这里下发的 `Cache-Control` 决定，干净可控。
"""

from __future__ import annotations

import mimetypes
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.api.v1.routes.auth import get_current_user
from app.core import file_storage
from app.models.user import User

router = APIRouter(prefix="", tags=["erp"])

# 图片落盘的实际子目录（相对 file_storage.storage_root()）
PRODUCT_IMAGE_SUBDIR = "products"

# 单张商品图片上限。比 file_storage.MAX_UPLOAD_BYTES（20MB，是给发票扫描件留的）
# 严得多：商品档案里的照片是给人看的，5MB 已经远超正常需求，设个紧一点的上限
# 能挡住"把手机原图直接拖进来"这种几十 MB 的误操作。
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# 对外允许的图片后缀。**刻意不含 .gif** —— file_storage 的后缀白名单里没有 .gif，
# 传进去会被它改写成 .bin，读出来就没法当图片用了。宁可明确拒绝并说清原因，
# 也不要静默产出一个打不开的文件。
ACCEPTED_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# 返回的 URL 长度上限。`products.image_url` 是 String(255)，留 15 字符余量。
#
# ⚠️ 为什么必须卡这个：`file_storage.safe_filename` 允许文件名主干**保留 80 个字符**，
# 而且刻意保留中文（发票扫描件常常就是中文名）。但 URL 里要做百分号编码，
# 一个汉字变 3 倍 —— 80 个汉字 = 240 字符，加上
# `/api/v1/uploads/products/`（26）+ uuid 前缀（12+1）+ 后缀，**会超过 255**，
# 于是"商品能存、图片也能存，但保存商品时数据库报长度溢出"。
# 实测按这个上限收敛后，返回的 URL 恒在 240 字符以内。
MAX_IMAGE_URL_CHARS = 240

# `file_storage.save_bytes` 会在文件名前面再拼一个 12 位随机 hex + "-"，共 13 个字符。
# 算 URL 预算时**必须把这 13 个字符算进去** —— 漏掉它的后果实测过：
# 自认为收敛到 240 以内，实际落盘后 URL 是 249，逼近列宽上限。
# 这里取上界（真值只会更短），将来那个模块改成更短的 uuid 也不用改这里。
STORED_NAME_PREFIX_CHARS = 13


def sniff_image_suffix(payload: bytes) -> str | None:
    """按**文件头**判断真实格式，返回规范后缀；不是图片则返回 None。

    只信文件头，不信客户端给的 `Content-Type` 和文件名后缀 —— 那两个都是调用方
    说了算的。顺带把 `.jpeg` 归一成 `.jpg`、把"后缀与内容不符"的文件纠正过来：
    否则会拿 `image/png` 的响应头去发一堆 JPEG 字节。
    """
    if len(payload) < 12:
        return None
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return ".webp"
    # BMP 的魔数只有 "BM" 两个字节，太弱（任何以 B、M 开头的文本都会命中），
    # 所以再校一下偏移 6 的"保留字段必须为 0"，这才有实际区分度。
    if payload.startswith(b"BM") and payload[6:8] == b"\x00\x00":
        return ".bmp"
    if payload[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return None


def public_image_url(rel_path: str) -> str:
    """落盘相对路径 → 可直接放进 `<img src>` 的地址。

    **返回相对路径、不返回绝对 URL**：本系统可能从 127.0.0.1、局域网 IP、
    或将来某个域名访问，把 host 写进库里会让换地址后所有图片一起失效。

    **URL 里做百分号编码、磁盘上仍保留中文原名**：
    落盘文件名沿用 file_storage 的既有约定（保留中文，便于人工翻 `data/products/`
    时认得出是什么），但 HTTP 请求行只允许 ASCII —— 实测不带自动编码的客户端
    （curl / 脚本）拿到含中文的 URL 会直接抛 `UnicodeEncodeError`。
    浏览器虽然会自己编码，但把 URL 存进库里、以后再被打印模板或导出功能复用，
    就不一定还有浏览器帮忙了。所以这里直接给出编码后的、任何客户端都能用的形式。

    注意不会双重编码：浏览器与 `fetch` 都会原样保留合法的 `%XX` 转义序列。
    """
    return "/api/v1/uploads/" + urllib.parse.quote(rel_path)


def fit_stem_to_url_budget(stem: str, suffix: str) -> str:
    """把文件名主干截短，直到编码后的 URL 不超过 MAX_IMAGE_URL_CHARS。

    见 `MAX_IMAGE_URL_CHARS` 的注释：不收敛的话，"很长的中文文件名"会让
    URL 超过 `products.image_url` 的 255 列宽，错误会推迟到用户点「保存」时才爆，
    报的还是一句很难懂的数据库长度溢出。
    """
    while len(stem) > 1:
        # 预算里必须算上 uuid 前缀：真名是 f"{uuid[:12]}-{name}"，占 13 个字符，
        # 而它由 file_storage 拼接，在本函数之外。用 13 个 'x' 占位（纯 ASCII，编码后不膨胀）
        probe = f"{PRODUCT_IMAGE_SUBDIR}/{'x' * STORED_NAME_PREFIX_CHARS}{stem}{suffix}"
        if len(public_image_url(probe)) <= MAX_IMAGE_URL_CHARS:
            break
        stem = stem[:-1]
    return f"{stem}{suffix}"


@router.post(
    "/upload/product-image",
    status_code=status.HTTP_201_CREATED,
    summary="上传商品图片",
)
async def upload_product_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
) -> dict[str, object]:
    """接收一张商品图片，落盘并返回可写进 `products.image_url` 的地址。

    只负责"存下来并给个地址"这条路，**不碰数据库** —— 所以新增商品时也能用：
    此时商品还没有 id，先把图传上来拿到地址，再随表单一起提交。
    """
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="上传的图片是空的")
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"图片 {len(payload) / 1024 / 1024:.1f}MB 超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB 上限",
        )

    suffix = sniff_image_suffix(payload)
    if suffix is None:
        raise HTTPException(
            status_code=400,
            detail="这不是一张图片（只支持 png / jpg / webp / bmp）",
        )
    if suffix == ".gif":
        raise HTTPException(
            status_code=400,
            detail="暂不支持 GIF 动图，请换成 png / jpg / webp / bmp",
        )

    # 文件名 = 净化后的原名 + **嗅探出来的**后缀（内容说了算，不是扩展名说了算），
    # 再把主干收敛到"编码后的 URL 不超列宽"的长度（见 MAX_IMAGE_URL_CHARS）
    stem = Path(file_storage.safe_filename(file.filename or "image")).stem
    stored_name = fit_stem_to_url_budget(stem, suffix)
    try:
        rel_path = file_storage.save_bytes(payload, stored_name, subdir=PRODUCT_IMAGE_SUBDIR)
    except ValueError as exc:
        # file_storage 自己也有一道上限校验，兜住它，别变成 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    url = public_image_url(rel_path)
    return {
        "url": url,
        "path": rel_path,
        "filename": Path(rel_path).name,
        "size": len(payload),
        "content_type": mimetypes.guess_type(rel_path)[0] or "application/octet-stream",
        # 回给前端的自证：这个地址能塞进 products.image_url（String(255)）
        "url_length": len(url),
    }


@router.get("/uploads/products/{filename}", summary="读取商品图片")
def read_product_image(filename: str) -> Response:
    """把落盘的商品图片读出来，供 `<img src>` 直接引用（**刻意不鉴权**，见模块头注释）。

    这里用显式路由而不是 `StaticFiles` 挂载：`app/main.py` 末尾 `mount("/", ...)`
    会吞掉所有路径，任何新挂载点都得插到它前面，顺序错了就是"有路由却 404"。
    """
    if (
        not filename
        or filename.startswith(".")
        or "\\" in filename
        or ".." in filename
        or "/" in filename
    ):
        # 路径参数本身不会包含 "/"，但反斜杠与 ".." 能进来 —— 先在 HTTP 层挡一次。
        # 真正的越界防护在 file_storage.absolute_path() 里（它会 resolve 后比对前缀）。
        raise HTTPException(status_code=404, detail="图片不存在")

    payload = file_storage.read_bytes(f"{PRODUCT_IMAGE_SUBDIR}/{filename}")
    if payload is None:
        raise HTTPException(status_code=404, detail="图片不存在")

    return Response(
        content=payload,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        headers={
            # 文件名自带 12 位随机 uuid 前缀，内容永不改变 → 可以放心长缓存。
            # 换图会拿到一个新文件名，所以不存在"换了图、浏览器还在用旧的"。
            "Cache-Control": "public, max-age=31536000, immutable",
            # 托管的是用户上传的文件，明确禁止浏览器猜类型：
            # 万一有个 .png 其实不是图片，也不要让它被当成别的类型去解释。
            "X-Content-Type-Options": "nosniff",
        },
    )
