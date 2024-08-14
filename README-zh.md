# AWS CloudFormation StackSet PowerTools
AWS CloudFormation StackSet 允许你通过一次操作在多个 AWS 账户和区域中配置 AWS CloudFormation 栈。这个功能对于需要在不同环境中保持一致性的大型组织或在多账户设置中管理资源特别有用。

但是在某些场景下，用户仍需要执行一些不易通过CloudFormation Console进行的复杂操作。这个基于Flask制作的简易运维工具可以简化大规模StackSet的操作和维护工作。

## 功能

1. **列出StackSets**: 显示组织内所有活动的Service-managed StackSets。
2. **添加未部署的账户**: 识别并添加组织内未部署StackSet的账户。
3. **删除挂起的账户**: 从已挂起的账户中删除StackSet实例。
4. **重试失败/漂移的实例**: 重试已失败或漂移的StackSet实例。

## 使用场景

- **集中管理StackSet**: 简化跨多个AWS账户管理CloudFormation StackSet。
- **自动化合规**: 确保组织内所有账户都部署了所需的StackSet。
- **错误恢复**: 轻松识别并重新部署失败或漂移的StackSet实例。
- **资源清理**: 从挂起的账户中删除StackSet实例，保持清洁的环境。

## 安装

1. **克隆仓库:**

   ```bash
   git clone https://github.com/your-repo/aws-cloudformation-powertools.git
   cd aws-cloudformation-powertools
   ```

2. **安装依赖:**

   ```bash
   pip install -r requirements.txt
   ```

3. **设置环境变量:**

   ```bash
   export AWS_ACCESS_KEY_ID=your_access_key_id
   export AWS_SECRET_ACCESS_KEY=your_secret_access_key
   export AWS_SESSION_TOKEN=your_session_token
   export AWS_DEFAULT_REGION=your_aws_region
   ```
   或使用[aws-vault](https://github.com/99designs/aws-vault) 工具进行设置

4. **运行应用程序:**

   ```bash
   python app.py
   ```
   或者使用gunicorn运行：
   ```
   gunicorn -w 4 -b 127.0.0.1:1980 app:app
   ```
5. **访问应用程序:**

   打开浏览器并导航到 `http://localhost:1980`。

## API端点

- **`GET /get_organization_accounts`**: 获取组织中所有账户的列表。
- **`POST /add_undeployed_accounts`**: 向未部署的账户添加StackSet实例。
- **`POST /remove_suspended_accounts`**: 从挂起的账户中删除StackSet实例。
- **`POST /retry_failed_instances`**: 重试失败的StackSet实例。
- **`POST /retry_drifted_instances`**: 重试漂移的StackSet实例。
- **`POST /get_in_sync_instances`**: 获取同步的实例。
- **`POST /get_drifted_instances`**: 获取漂移的实例。
- **`POST /get_succeeded_instances`**: 获取成功的实例。
- **`POST /get_failed_instances`**: 获取失败的实例。
- **`POST /get_skipped_suspended_account_instances`**: 获取跳过/挂起账户的实例。

## 贡献

欢迎贡献！请提出问题或提交拉取请求，以进行任何改进或错误修复。

## 许可证

该项目使用MIT许可证。