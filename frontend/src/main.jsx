import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './tokens.css';   // 设计令牌：只定义 :root 变量，必须在业务样式之前载入
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
