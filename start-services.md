# 如何正确启动 Coiner 服务

## 步骤 1：启动后端服务

1. 打开一个终端窗口
2. 进入项目目录：
   ```bash
   cd D:\src\Coiner
   ```
3. 激活 conda 环境：
   ```bash
   conda activate condaenv-moneyprinter
   ```
4. 启动后端服务：
   ```bash
   python main.py
   ```
   或使用 uvicorn：
   ```bash
   python -m uvicorn app.asgi:app --host 0.0.0.0 --port 8000
   ```

5. 确认后端服务已成功启动，应该看到类似以下输出：
   ```
   start server, docs: http://127.0.0.1:8000/docs
   ```

## 步骤 2：启动前端服务

1. 打开另一个终端窗口
2. 进入项目目录：
   ```bash
   cd D:\src\Coiner
   ```
3. 启动前端服务：
   ```bash
   .\webui.bat
   ```

4. 确认前端服务已成功启动，应该看到类似以下输出：
   ```
   Starting development server at http://localhost:3000/
   ```

## 步骤 3：验证服务是否正常运行

1. 打开浏览器，访问前端服务：
   ```
   http://localhost:3000/
   ```

2. 检查浏览器控制台是否有任何错误信息

3. 尝试访问后端 API 端点：
   ```
   http://localhost:8000/api/v1/config
   ```
   应该返回配置信息的 JSON 响应

## 常见问题排查

1. **后端服务启动失败**：
   - 检查依赖是否安装：`pip install -r requirements.txt`
   - 检查端口 8000 是否被占用
   - 检查是否有导入错误或其他错误信息

2. **前端服务启动失败**：
   - 检查依赖是否安装：`npm install`
   - 检查端口 3000 是否被占用
   - 检查 TypeScript 编译错误

3. **前端无法连接到后端**：
   - 确保后端服务已成功启动
   - 确保网络连接正常
   - 检查 API 基础 URL 配置是否正确

4. **配置文件无法加载**：
   - 确保 `config.toml` 文件存在且格式正确
   - 检查配置文件中的必要配置项是否存在
   - 确保后端服务有读取配置文件的权限
