# AWS CloudFormation StackSet PowerTools

AWS CloudFormation StackSet allows you to provision AWS CloudFormation stacks across multiple AWS accounts and regions with a single operation. This feature is particularly useful for large organizations that need to maintain consistency across different environments or for managing resources in a multi-account setup.

However, in certain scenarios, users still need to perform some complex operations that are not easily done through the CloudFormation Console. This simple operations tool, based on Flask, can simplify the operations and maintenance work of large-scale StackSets.

## Features

1. **List StackSets**: Display all active Service-managed StackSets within the organization.
2. **Add Undeployed Accounts**: Identify and add accounts within the organization that do not have the StackSet deployed.
3. **Remove Suspended Accounts**: Remove StackSet instances from accounts that have been suspended.
4. **Retry Failed/Drifted Instances**: Retry StackSet instances that have failed or drifted from the desired state.

## Usage Scenarios

- **Centralized StackSet Management**: Simplify the management of CloudFormation StackSets across multiple AWS accounts within an organization.
- **Automated Compliance**: Ensure all accounts within the organization have the required StackSets deployed.
- **Error Recovery**: Easily identify and redeploy failed or drifted StackSet instances.
- **Resource Cleanup**: Remove StackSet instances from suspended accounts to maintain a clean environment.

## Installation

1. **Clone the repository:**

   ```bash
   git clone https://github.com/your-repo/aws-cloudformation-powertools.git
   cd aws-cloudformation-powertools
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**

   ```bash
   export AWS_ACCESS_KEY_ID=your_access_key_id
   export AWS_SECRET_ACCESS_KEY=your_secret_access_key
   export AWS_SESSION_TOKEN=your_session_token
   export AWS_DEFAULT_REGION=your_aws_region
   ```
   or set env with [aws-vault](https://github.com/99designs/aws-vault) utility

4. **Run the application:**

   ```bash
   python app.py
   ```
   or run app using gunicorn:
   ```
   gunicorn -w 4 -b 127.0.0.1:1980 app:app
   ```

5. **Access the application:**

   Open your web browser and navigate to `http://localhost:1980`.

## API Endpoints

- **`GET /get_organization_accounts`**: Get a list of all accounts in the organization.
- **`POST /add_undeployed_accounts`**: Add StackSet instances to undeployed accounts.
- **`POST /remove_suspended_accounts`**: Remove StackSet instances from suspended accounts.
- **`POST /retry_failed_instances`**: Retry failed StackSet instances.
- **`POST /retry_drifted_instances`**: Retry drifted StackSet instances.
- **`POST /get_in_sync_instances`**: Get instances that are in sync.
- **`POST /get_drifted_instances`**: Get drifted instances.
- **`POST /get_succeeded_instances`**: Get succeeded instances.
- **`POST /get_failed_instances`**: Get failed instances.
- **`POST /get_skipped_suspended_account_instances`**: Get skipped/suspended account instances.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.

## License

This project is licensed under the MIT License.