/* ERP PWA 鏈嶅姟宸ヤ綔鑰?
 *
 * 浣滅敤锛?
 * 1. 棣栨瀹夎鏃剁紦瀛樺簲鐢ㄥ澹筹紙椤甸潰銆佸浘鏍囥€佹竻鍗曪級
 * 2. 闈欐€佽祫婧愶細浼樺厛鐢ㄧ紦瀛橈紙绂荤嚎涔熻兘鎵撳紑锛夛紝鍚庡彴鎮勬倓鏇存柊
 * 3. 涓氬姟鎺ュ彛 /api锛氭案杩滆蛋缃戠粶锛屼笉缂撳瓨锛堜繚璇佹暟鎹疄鏃讹級
 *
 * 娉ㄦ剰锛氭敼浜嗙増鏈彿 CACHE_VERSION 鍚庯紝鏃х紦瀛樹細鑷姩娓呯悊锛坅ctivate 閲屽垹鎺夋墍鏈夐潪褰撳墠鐗堟湰锛夈€?
 *
 * 浠€涔堟椂鍊欒 bump锛?*姣忔鍙戝竷**閮藉缓璁?+1銆傚巻鍙叉暀璁細
 * 杩欎釜鍊兼浘缁忛暱鏈熷仠鍦?'erp-pwa-v1'锛岃€?shell 缂撳瓨閲屽瓨鐫€ '/'(index.html)锛?
 * 浜庢槸娴忚鍣ㄤ竴鐩存嬁鐫€鏃ч椤?鈫?鎸囧悜鏃?hash 鐨?js 鈫?鍓嶇鏄庢槑閲嶆柊鏋勫缓浜嗗嵈銆屾敼浜嗘病鍙樺寲銆嶃€?
 * 鐜板湪鏈嶅姟绔凡缁?index.html / sw.js 鍙?`Cache-Control: no-cache`锛堣 app/main.py 鐨?
 * CacheControlledStaticFiles锛夛紝bump 鐗堟湰鍙峰彧鏄?*鍏滃簳**锛岄槻姝㈣€佸鎴风娈嬬暀銆?
 *
 * v2 鈫?v3锛?026-10-15锛夛細渚ц竟鏍忚彍鍗曞瓧浣撴敼鐗堛€俠ump 鍚?activate 浼氬垹鎺?
 * 'erp-pwa-v2-shell'锛堥噷闈㈠瓨鐫€鏃?'/'锛夛紝鑰佸鎴风涓嬫瀵艰埅鍗宠嚜鍔ㄦ仮澶嶃€?
 * 鍚屾椂鎶婂鑸姹傛敼鎴?`cache: 'no-store'`锛岃 index.html 姘镐笉浠?HTTP 缂撳瓨閲屽彇銆?
 * v3 鈫?v4锛?026-10-16锛夛細鑿滃崟鏍戠紪杈戝櫒鎺ュ叆鑿滃崟绠＄悊椤碉紙鏂板鎸夐渶 chunk锛夈€?
 * v4 鈫?v5锛?026-10-16锛夛細鍟嗗搧妗ｆ宸︿晶绫诲埆鏍戯紙鏂板 lib/productCategory + 缁勪欢锛夈€?
 * v5 鈫?v6锛?026-10-16锛夛細鍟嗗搧寮圭獥鎶芥垚鐙珛缁勪欢骞舵柊澧炲浘鐗囨湰鍦颁笂浼犻瑙?
 *   锛堟柊澧?lib/productImage + components/product-edit锛夈€傚浘鐗囨湰韬蛋
 *   /api/v1/uploads/*锛屽懡涓嶄腑鏈?SW 鐨?fetch 鎷︽埅锛?api/ 寮€澶寸洿鎺?return锛夛紝
 *   鎵€浠ュ浘鐗囩殑缂撳瓨鐢卞悗绔笅鍙戠殑 Cache-Control 鍐冲畾锛岃繖閲屼笉鐢ㄧ銆?
 * v6 鈫?v7锛?026-10-16锛夛細鍟嗗搧鍒楄〃鏂板棣栧垪銆屽浘鐗囥€嶇缉鐣ュ浘 + 绉婚櫎姝讳唬鐮?
 *   flattenCategories銆傝〃鏍煎垪鍙锋暣浣撳悗绉讳竴浣嶏紝CSS 鐨?nth-child 瑙勫垯鍚屾鏀逛簡锛?
 *   鑰佸鎴风鑻ョ紦瀛樹簡鏃?CSS/JS锛屼細鍑虹幇"琛ㄥご 13 鍒椼€佸唴瀹?12 鏍?鐨勯敊浣?
 *   鈥斺€?杩欎竴鐗堝繀椤?bump锛屼笉鑳界渷銆?
 * v7 鈫?v8锛?026-10-16锛夛細鍟嗗搧寮圭獥鏂板銆岃緟鍔╁崟浣嶄笌鎹㈢畻銆嶇淮鎶ゅ尯
 *   锛堟柊澧?lib/productUnits + components/product-edit/ProductUnitsField锛夈€?
 *   bump 鐨勫師鍥犱笉鍙槸"鏈夋柊浠ｇ爜"锛?*銆屽寘瑁呮暟銆嶈繖涓緭鍏ユ浠庡彲缂栬緫鏀规垚浜嗗彧璇?*锛?
 *   鑰屼笖寮圭獥搴曢儴澶氫簡涓€鏁村潡琛ㄥ崟銆傝€佸鎴风鎷跨潃鏃?JS 鎵撳紑寮圭獥鏃讹紝鐢ㄦ埛浼氱湅鍒?
 *   涓€涓?鏀逛簡涓嶇敓鏁?鐨勫寘瑁呮暟杈撳叆妗?鈥斺€?閭ｆ瘮鎶ラ敊鏇撮毦鎺掓煡銆?
 * v8 鈫?v9锛?026-10-17锛夛細鍗曟嵁鏄庣粏琛?+ 鍟嗗搧鏈熷垵搴撳瓨鐨勫晢鍝侀€夋嫨鎹㈡垚鍙悳绱㈢殑
 *   SearchSelect锛涘晢鍝佹。妗堝乏鏍忕被鍒爲瀹氬銆?*杩欐鐨勬暀璁繀椤昏涓嬫潵**锛氭敼瀹屽繕浜?
 *   bump锛屾瀯寤烘垚鍔熴€乨ist 涔熸崲浜?hash锛岀敤鎴峰埛鏂扮湅鍒扮殑鍗磋繕鏄師鐢?<select> 鈥斺€?
 *   Service Worker 鎷?v8 鐨勬棫缂撳瓨鎶?index.html 鍘熸牱杩樺洖鍘讳簡銆?
 *   鍒ゅ畾鏂规硶锛堜笉瑕佽烦杩囷級锛歚grep -o 'combobox' dist/assets/index-*.js` 鏈夊懡涓€?
 *   椤甸潰涓婂嵈娌℃湁鏂扮粍浠?鈬?灏辨槸 SW 缂撳瓨锛宐ump 鐗堟湰鍙枫€?
 * v9 鈫?v10锛?026-10-17锛屽悓鏃ョ浜屼釜鍙戝竷锛夛細Excel 瀵煎叆瀵煎嚭椤靛崱鐗囧瓧闃剁粺涓€銆?
 *   鍚屼竴澶╄繛鍙戜袱鐗堟椂**姣忕増閮借 bump**锛歷9 缂撳瓨閲屽瓨鐫€鐨勮€?index.html 浼氭寚鍚?
 *   宸茬粡琚?`vite build` 娓呮帀鐨勬棫 hash 鏂囦欢鍚嶏紝鏂綉鍥為€€鏃朵細鐧藉睆銆?
 *   椤哄甫婢勬竻涓€涓鏄撹鍒ょ殑鐐癸細鏈?SW 鐨?*椤甸潰瀵艰埅鏄€岀綉缁滀紭鍏?+ no-store銆?*锛?
 *   鎵€浠ュ彧瑕佺敤鎴风湡鎸変簡 F5锛宨ndex.html 涓€瀹氭槸鏂扮殑锛涗粬鐪嬪埌鏃х晫闈㈤€氬父鏄?
 *   "SPA 涓€鐩存病鏁撮〉鍒锋柊"锛堝垏鑿滃崟涓嶄細瑙﹀彂 navigation锛夈€傞潤鎬佽祫婧愰偅鏉℃墠鏄?
 *   缂撳瓨浼樺厛锛屽洜姝?bump 浠嶇劧蹇呰銆?
 * v10 鈫?v11锛?026-10-17锛屽悓鏃ョ涓変釜鍙戝竷锛夛細鍏ㄥ眬闈㈡澘鎷栨嫿锛堟柊澧?
 *   components/resizable-layout锛屾浛鎹?35 澶?management-grid锛夈€?
 *   杩欎竴鐗?*蹇呴』鍏?bump 鍐嶈鐢ㄦ埛鐪嬫晥鏋?*锛氳€佸鎴风閲屾病鏈?ResizableLayout锛?
 *   JS 鏄棫鐨勶紙琛ㄦ牸甯冨眬鐓ф棫锛夛紝鐢ㄦ埛浼氫互涓?鎷栨嫿鏍规湰娌″仛"銆?
 * v11 鈫?v12锛?026-10-17锛屽悓涓€鍔熻兘淇鐗堬級锛氫慨浜嗕袱涓彧鏈夌湡娴忚鍣ㄦ墠鏆撮湶鐨勯棶棰?鈥斺€?
 *   鈶?缁勪欢 CSS 琚?Vite 鎻愬埌 styles.css 涔嬪墠锛屽悓鐗瑰紓鎬т笅 `.management-grid`
 *      鍙嶅帇鎴愬姛锛岀綉鏍间粛鏄?2 鍒椼€佹墜鏌勮濉炶繘绗簩琛岋紙= 鐢ㄦ埛鎶ョ殑"鎷栦笉鍔?锛夈€?
 *      閫夋嫨鍣ㄥ崌绾ф垚 `.management-grid.mgrid--split`锛?,2,0锛夈€?
 *   鈶?pointerdown 閲岀殑 preventDefault 鍘嬫帀浜?mousedown/click 搴忓垪锛?
 *      瀵艰嚧 onDoubleClick 姘歌繙涓嶈Е鍙戯紙鍙屽嚮鎭㈠榛樿鏄鐨勶級銆?
 *      鎵嬫焺鐐瑰畬涔熸嬁涓嶅埌鐒︾偣锛堟柟鍚戦敭寰皟澶辨晥锛夈€?
 *   涓ゅ閮芥槸"鏋勫缓鎴愬姛銆侀〉闈㈣兘寮€銆佸氨鏄笉瀵?鐨勫吀鍨嬶紝蹇呴』 bump銆?
 * v12 鈫?v13锛?026-10-17锛岀浜屾绀鸿寖閲嶆瀯锛夛細鍟嗗搧妗ｆ椤垫暣椤垫崲鎴?ErpCard 脳 2 +
 *   ErpTable + EmptyState锛屽晢鍝佸脊绐椾袱濂楄〃鍗曞悎骞舵垚涓€濂?ErpFormGrid銆?
 *   鑰佸鎴风 JS 閲岃繕鏄?section.panel + 鎵嬪啓琛ㄦ牸锛岀敤鎴蜂細鐪嬪埌"閲嶆瀯娌＄敓鏁?銆?
 * v13 鈫?v14锛?026-10-17锛岀涓夋-A锛氬鎴?渚涘簲鍟嗘。妗堬級锛氫袱椤典粠銆屽崟鏍?data-table銆?
 *   鎹㈡垚 ErpCard 脳 2 + ErpTree 鍒嗙粍鏍?+ ErpTable锛屽脊绐楁崲鎴?ErpFormGrid銆?
 *   椤甸潰缁撴瀯鍙樺姩寰堝ぇ锛堝浜嗗乏渚ф爲涓庢嫋鎷芥墜鏌勶級锛屽繀椤?bump銆?
 * v14 鈫?v15锛?026-10-17锛岀涓夋-B锛氶噰璐叆搴擄級锛氭槑缁嗚浠?`.form-row.four-col`
 *   鎹㈡垚 ErpTable dense锛坮ender 鎻掓Ы鏀炬帶浠?+ footer 鍚堣锛夛紝琛ㄥご鎹?ErpFormGrid銆?
 *   鑰佸鎴风 JS 閲岃繕鏄洓鍒楄〃鍗曡锛屽繀椤?bump銆?
 * v15 鈫?v16锛?026-10-17锛屾竻缂撳瓨 + 閲嶆柊鎵撳寘锛夛細鏈鏃犲姛鑳芥敼鍔紝绾补涓轰簡璁╂墍鏈?
 *   宸插紑鐫€鐨勫鎴风鍦ㄤ笅娆″鑸椂涓㈡帀鏃?shell 缂撳瓨銆佹崲鎴愯繖娆￠噸鏂版瀯寤虹殑浜х墿
 *   锛坕ndex.html 鐨?hash 鍙樹簡锛岃€?SW 缂撳瓨閲岀殑 '/' 浼氭寚鍚戝凡缁忎笉瀛樺湪鐨勬棫 chunk锛夈€?
 * v16 鈫?v17锛?026-10-17锛岄攢鍞嚭搴撻噸鏋勶級锛歋alesPage 1196 琛?鈫?钖勫３锛?
 *   鏁撮〉 UI 鎼繘 components/docs/SalesOutboundBoard.jsx锛汦rpTable 鏂板鍙€夌殑
 *   `rowProps`锛堣ˉ鍥炲垪琛ㄨ Enter/绌烘牸 鎵撳紑璇︽儏鐨勯敭鐩樺彲杈炬€э級銆?
 *   杩欎竴鐗?*蹇呴』** bump锛氭槑缁嗚浠?`.form-row.four-col` 鍙樻垚 `.erp-table`锛?
 *   鏃?JS + 鏂?CSS锛堟垨鍙嶈繃鏉ワ級浼氳鏄庣粏琛ㄦ覆鏌撴垚涓€鍫嗘病鏈夎〃澶寸殑瑁歌緭鍏ユ銆?
 * v17 鈫?v18锛?026-10-17锛岃鍗曚袱椤甸噸鏋勶級锛歅urchaseOrderPage / SalesOrderPage 鍚?1133 琛?
 *   鈫?21 琛岃杽澹筹紝鏁撮〉 UI 杩?components/docs/OrderBoard.jsx锛堜袱椤靛叡鐢?CONFIG锛夈€?
 *   蹇呴』 bump 鐨勭悊鐢卞悓 v17锛氭槑缁嗚浠?`.form-row.three-col` 鍙樻垚 `.erp-table`锛?
 *   璁㈠崟鍒楄〃澶氫簡銆屽凡杞崟銆嶇伆鏍囥€佸皯浜嗘寜閽紝鏃?JS 閰嶆柊 CSS 浼氶敊浣嶃€?
 * v18 鈫?v19锛?026-10-17锛寁1.0.0 鍙戝竷锛氭竻閬撳か + 閲嶆墦妗岄潰鐗堬級锛?
 *   鈶?styles.css 鍒犳帀 3 缁勫凡鏃犲涓荤殑瑙勫垯锛堜袱鏉?:has() + 鍥?涓夊垪缃戞牸閲嶅啓锛夛紝
 *      鍏ㄥ眬 `.form-row.three-col`(12 椤? / `.form-row.four-col` 鍘熸牱淇濈暀锛?
 *   鈶?淇帀 v18 閭ｆ鐨勬敞閲婃敹灏?鈥斺€?涓婁竴鐗堟妸缁撴潫瀹氱晫绗﹀啓鍦ㄤ簡娈佃惤涓棿锛堟槦鍙?鏂滄潬
 *      鍗曠嫭鍗犱竴琛岋級锛屽鑷存湰鏂囦欢**涓嬫柟鍏ㄩ儴鏄娉曢敊璇?*锛孲W 浠?v18 璧峰氨娌℃敞鍐屾垚鍔?
 *      杩囷紙`node --check sw.js` exit 1锛夈€傚啓杩欑被娉ㄩ噴鏃跺姟蹇呭埆鎶婄粨鏉熷畾鐣岀鍐欒繘姝ｆ枃銆?
 *   蹇呴』 bump锛欳SS 鍐呭鍙樹簡锛岃€佸鎴风 shell 缂撳瓨閲岀殑 index-*.css 鏄棫 hash銆?
 * v19 鈫?v20锛?026-10-17锛岀涓€闃舵 Step 1锛氬鎴?渚涘簲鍟嗐€岀紪杈戙€嶉棴鐜級锛?
 *   涓ら〉鐨勫垪琛ㄦ搷浣滃垪澶氫簡銆岀紪杈戙€嶆寜閽紝寮圭獥浠?鍙湁鏂板"鍙樻垚"鏂板 / 缂栬緫鍙屾ā"锛?
 *   缂栫爜鍦ㄧ紪杈戞€佸彧璇伙紱鍚庣鏂板 PATCH /customers/{id} 涓?PATCH /suppliers/{id}銆?
 *   蹇呴』 bump锛氳€佸鎴风 JS 閲屾病鏈?partner-edit-btn銆佷篃涓嶇煡閬?PATCH 鎬庝箞鍙戯紝
 *   鐢ㄦ埛鐐广€岀紪杈戙€嶄細鏄交搴曟病鍙嶅簲 鈥斺€?杩欑"鍔熻兘鍍忔病鍋?鏈€闅捐嚜璇侊紝鍏?bump 鍐嶈浜虹湅銆?
 *   鍚屾棩娉ㄦ剰锛氭湰鐗堝彧鏄?Step 1锛孲tep 2锛圗rpTable 澶氶€夛級钀藉湴鍚庤繕瑕佸啀 bump 涓€娆°€?
 * v20 鈫?v21锛?026-10-17锛岀涓€闃舵 Step 2锛欵rpTable 澶氶€?+ 鎵归噺鍒犻櫎锛夛細
 *   鍟嗗搧/瀹㈡埛/渚涘簲鍟嗗垪琛ㄦ渶宸︿晶澶氫簡涓€鍒?Checkbox锛堣〃澶村甫鍏ㄩ€?鍗婇€夛級锛屾湁閫変腑鏃?
 *   琛ㄦ牸涓婃柟娴嚭銆屽凡閫変腑 N 椤?+ 鎵归噺鍒犻櫎銆嶏紱鎵归噺鍒犻櫎璧版棭宸插瓨鍦ㄧ殑
 *   `/products|/customers|/suppliers/batch`锛屾寜 deleted/blocked 鍒嗗紑鎶ユ暟銆?
 *   蹇呴』 bump锛氳€佸鎴风 JS 閲屾病鏈夐€夋嫨鍒楋紝涔熸病鏈?bulkbar 鐨?CSS 鈥斺€?
 *   鐢ㄦ埛浼氫互涓?澶氶€夋病鍋?銆傝〃鏍煎垪鏁颁篃鏁翠綋鍚庣Щ涓€浣嶏紝鏃?CSS 閰嶆柊 DOM 浼氶敊浣嶃€?
 * v151 鈫?v152锛?026-10-21锛屽皝鐗堟敹灏撅級锛?
 *   宸︿晶鍒嗙被鏍戞敼閫狅紙鍒嗙被涓嬪钩閾哄鎴峰彾瀛?+ 鍚岀骇鎵嬮鐞存姌鍙?+ 鎷栨嫿鍚庤嚜鍔ㄥ睍寮€瀹氫綅锛夈€?
 *   瀹㈡埛/渚涘簲鍟?鍟嗗搧涓夎〃鍒楀鍙嫋骞舵寔涔呭寲銆佹嫋鎷藉綊妗ｏ紙瀹㈡埛/渚涘簲鍟?鍟嗗搧锛夈€?
 *   寮圭獥銆屾墍灞炲垎绫汇€嶆爲褰笅鎷夊洖鏄句慨澶嶃€?
 *   蹇呴』 bump锛氳€佸鎴风缂撳瓨鐫€鏃?index-*.js锛岄噷闈㈡病鏈?.ptree__leaf / 鍒楀鎶撴墜锛?
 *   鐢ㄦ埛浼氱湅鍒?鏍戣繕鏄函鐩綍銆佽〃澶存嫋涓嶅姩"鈥斺€?涔熷氨鏄?鏀逛簡娌″彉鍖?銆?
 * v253 鈫?v254锛?026-10-24锛屽悎鍚岄〉鏀跺熬锛夛細
 *   鍚堝悓宸︿晶琛ㄥ崟鏂眰浜屾鍔犲浐 + 妯℃澘搴撳菇鐏佃褰曡嚜鍔ㄦ竻鎵?+ 鏃犲彉閲忔ā鏉垮墠缃眹鎬婚〉銆?
 *   蹇呴』 bump锛歷253 缂撳瓨閲岀殑 index-*.css 鏄?10-24 10:50 涔嬪墠鐨勬棫 hash锛?
 *   stale-while-revalidate 浼氬厛鎶婃棫鏍峰紡杩樼粰鐢ㄦ埛 鈥斺€?鐢ㄦ埛鎶ュ憡"鏂眰淇簡杩樺湪"銆?
 *   bump 鍚?activate 鐩存帴鍒犳棫缂撳瓨锛屼笅娆″鑸繀鐒舵嬁鍒版渶鏂版瀯寤恒€?*/

const CACHE_VERSION = 'erp-pwa-v299';
const CACHE_NAME = `${CACHE_VERSION}-shell`;

// 搴旂敤澶栧３锛氱绾挎墦寮€鑷冲皯瑕佹湁鐨勬枃浠?
const APP_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

// 瀹夎锛氶缂撳瓨搴旂敤澶栧３
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// 婵€娲伙細鍒犻櫎鏃х増鏈紦瀛?
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// 璇锋眰鎷︽埅绛栫暐
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 涓氬姟鎺ュ彛锛氬彧璧扮綉缁滐紝澶辫触鏃惰繑鍥炴彁绀猴紙涓嶇紦瀛樼湡瀹炴暟鎹級
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // 椤甸潰瀵艰埅锛氱綉缁滀紭鍏堬紙寮哄埗 cache:'no-store'锛岀粫杩?HTTP 缂撳瓨锛夛紝鏂綉鏃堕€€鍥炵紦瀛橀椤?
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(() => caches.match('/'))
    );
    return;
  }

  // 鍏朵粬闈欐€佽祫婧愶細缂撳瓨浼樺厛 + 鍚庡彴鏇存柊锛坰tale-while-revalidate锛?
  if (event.request.method === 'GET') {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const network = fetch(event.request)
          .then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) =>
              cache.put(event.request, copy)
            );
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })
    );
  }
});
