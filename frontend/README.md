# Trip Planner Frontend

Vue 3 + TypeScript + Vite 前端，用于提交旅行需求并展示后端生成的行程。

## 本地启动

```powershell
npm install
npm run dev
```

开发地址默认为 `http://localhost:5173`。Vite 会将 `/api` 和 `/health` 请求代理到
`http://127.0.0.1:8000`，可以通过 `.env` 中的 `VITE_BACKEND_URL` 修改。

## 后端接口约定

- `GET /health`：服务健康检查
- `POST /api/trip/plan`：生成旅行计划

请求和响应的 TypeScript 定义位于 `src/types/trip.ts`。后端模型发生变化时，优先同步这里，
组件不直接拼装接口字段。

## 常用命令

```powershell
npm run dev
npm run type-check
npm run build
npm run preview
```
