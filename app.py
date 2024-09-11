from flask import Flask, render_template, jsonify, request
import boto3
import os
import functools

app = Flask(__name__)

# 获取环境变量中的AWS身份信息和区域信息
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.getenv('AWS_SESSION_TOKEN')
aws_region = os.getenv('AWS_DEFAULT_REGION')

# 创建Boto3客户端
cloudformation_client = boto3.client(
    'cloudformation',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    aws_session_token=aws_session_token,
    region_name=aws_region
)

organizations_client = boto3.client(
    'organizations',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    aws_session_token=aws_session_token,
    region_name=aws_region
)

def get_organization_accounts():
    accounts = []
    paginator = organizations_client.get_paginator('list_accounts')
    for page in paginator.paginate():
        accounts.extend(page['Accounts'])
    return accounts

@app.route('/get_organization_accounts', methods=['GET'])
def get_organization_accounts_route():
    try:
        accounts = get_organization_accounts()
        accounts.sort(key=lambda x: x['Name'])  # 按名称排序
        return jsonify(accounts)
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@functools.lru_cache(maxsize=128)
def get_stack_instances(stack_set_name):
    instances = []
    next_token = None
    while True:
        if next_token:
            stack_instance_details = cloudformation_client.list_stack_instances(StackSetName=stack_set_name, CallAs='DELEGATED_ADMIN', NextToken=next_token)
        else:
            stack_instance_details = cloudformation_client.list_stack_instances(StackSetName=stack_set_name, CallAs='DELEGATED_ADMIN')
        
        instances.extend(stack_instance_details.get('Summaries', []))
        next_token = stack_instance_details.get('NextToken')
        if not next_token:
            break
    return instances

@app.route('/')
def list_stacksets():
    try:
        # 获取Service-managed的StackSets
        stack_sets = []
        next_token = None
        while True:
            if next_token:
                response = cloudformation_client.list_stack_sets(Status='ACTIVE', CallAs='DELEGATED_ADMIN', NextToken=next_token)
            else:
                response = cloudformation_client.list_stack_sets(Status='ACTIVE', CallAs='DELEGATED_ADMIN')
            
            stack_sets.extend(response.get('Summaries', []))
            next_token = response.get('NextToken')
            if not next_token:
                break

        # 获取组织中的所有账户
        organization_accounts = get_organization_accounts()
        total_organization_accounts = len(organization_accounts)
        
        # 获取所有StackSet的详细信息
        stack_set_details_list = []
        for stack_set in stack_sets:
            stack_set_name = stack_set['StackSetName']
            stack_set_details = cloudformation_client.describe_stack_set(StackSetName=stack_set_name, CallAs='DELEGATED_ADMIN')
            stack_set_info = stack_set_details['StackSet']
            
            auto_deployment = stack_set_info.get('AutoDeployment', {})
            
            # 获取stack instances的详细信息
            get_stack_instances.cache_clear()
            instances = get_stack_instances(stack_set_name)
            
            total_instances = len(instances)
            in_sync = sum(1 for instance in instances if instance['DriftStatus'] == 'IN_SYNC')
            drifted = sum(1 for instance in instances if instance['DriftStatus'] == 'DRIFTED')
            succeeded = sum(1 for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SUCCEEDED')
            failed = sum(1 for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'FAILED')
            skipped_suspended_account = sum(1 for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SKIPPED_SUSPENDED_ACCOUNT')
            
            # 计算未推送StackSet的账户
            deployed_account_ids = {instance['Account'] for instance in instances}
            not_deployed_accounts = [account for account in organization_accounts if account['Id'] not in deployed_account_ids]
            
            stack_set_details_list.append({
                'StackSetName': stack_set_name,
                'AutoDeployment': auto_deployment,
                'TotalInstances': total_instances,
                'InSync': in_sync,
                'Drifted': drifted,
                'Succeeded': succeeded,
                'Failed': failed,
                'SkippedSuspendedAccount': skipped_suspended_account,
                'NotDeployedAccounts': len(not_deployed_accounts),
                'NotDeployedAccountDetails': not_deployed_accounts
            })
        
        return render_template('list_stacksets.html', stack_set_details_list=stack_set_details_list)
    except Exception as e:
        return f"An error occurred: {str(e)}"

@app.route('/add_undeployed_accounts', methods=['POST'])
def add_undeployed_accounts():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        # Retrieve organization accounts
        organization_accounts = get_organization_accounts()
        organization_account_ids = {account['Id'] for account in organization_accounts}

        # Retrieve root OU ID
        root_ou_id = get_organization_root_ou_id()

        # List stack instances to get deployed accounts
        instances = get_stack_instances(stack_set_name)
        deployed_account_ids = {instance['Account'] for instance in instances}

        # Calculate undeployed account IDs
        undeployed_account_ids = organization_account_ids - deployed_account_ids - ignore_accounts
        undeployed_account_details = [account for account in organization_accounts if account['Id'] in undeployed_account_ids]
        
        # Dry run response
        if dry_run:
            return jsonify({'message': 'Dry run: following accounts would be added', 'accounts': undeployed_account_details})
        
        # Add undeployed accounts
        for account in undeployed_account_details:
            cloudformation_client.create_stack_instances(
                StackSetName=stack_set_name,
                DeploymentTargets={
                    'Accounts': [account['Id']],
                    'OrganizationalUnitIds': [root_ou_id],
                    'AccountFilterType': 'INTERSECTION'
                },
                Regions=[aws_region],
                CallAs='DELEGATED_ADMIN'
            )
            
        return jsonify({'message': 'Undeployed accounts added successfully.', 'accounts': undeployed_account_details})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

def get_organization_root_ou_id():
    try:
        response = organizations_client.list_roots()
        root_ou_id = response['Roots'][0]['Id']
        return root_ou_id
    except Exception as e:
        raise Exception(f"Failed to retrieve organization root OU ID: {str(e)}")

@app.route('/remove_suspended_accounts', methods=['POST'])
def remove_suspended_accounts():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        outdated_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SKIPPED_SUSPENDED_ACCOUNT' and instance['Account'] not in ignore_accounts
        ]
        
        account_statuses = {}
        for instance in outdated_instances:
            account_id = instance['Account']
            if account_id in ignore_accounts:
                continue
            try:
                account_status = organizations_client.describe_account(AccountId=account_id)['Account']['Status']
                if account_status != 'SUSPENDED':
                    outdated_instances.remove(instance)
            except Exception as e:
                account_status = 'Deleted'
            account_statuses[account_id] = account_status
        
        if not outdated_instances:
            return jsonify({'message': 'No suspended accounts found.'})
        
        # Combine instances with the same OrganizationalUnitId and Region
        combined_instances = {}
        for instance in outdated_instances:
            key = (instance['OrganizationalUnitId'], instance['Region'])
            instance['Status']=account_statuses[instance['Account']]
            if key not in combined_instances:
                combined_instances[key] = []
            combined_instances[key].append(instance)
        
        for (ou_id, region), accounts in combined_instances.items():
            if dry_run:
                return jsonify({'message': 'Dry run: following accounts would be removed', 'accounts': accounts})
            else:
                cloudformation_client.delete_stack_instances(
                    StackSetName=stack_set_name,
                    DeploymentTargets={
                        'Accounts': [account['Account'] for account in accounts],
                        'OrganizationalUnitIds': [ou_id],
                        'AccountFilterType': 'INTERSECTION',
                    },
                    Regions=[region],
                    RetainStacks=True,
                    CallAs='DELEGATED_ADMIN'
                )
        
                return jsonify({'message': 'Suspended accounts removed successfully.'})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/retry_failed_instances', methods=['POST'])
def retry_failed_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        failed_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'FAILED' and instance['Account'] not in ignore_accounts
        ]
        
        if not failed_instances:
            return jsonify({'message': 'No failed instances found.'})
        
        if dry_run:
            return jsonify({'message': 'Dry run: following instances would be retried', 'instances': failed_instances})
        
        for instance in failed_instances:
            cloudformation_client.update_stack_instances(
                StackSetName=stack_set_name,
                DeploymentTargets={
                    'Accounts': [instance['Account']],
                    'OrganizationalUnitIds': [instance['OrganizationalUnitId']],
                    'AccountFilterType': 'INTERSECTION',
                },
                Regions=[instance['Region']],
                CallAs='DELEGATED_ADMIN'
            )
        return jsonify({'message': 'Failed instances retried successfully.', 'instances': failed_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/retry_drifted_instances', methods=['POST'])
def retry_drifted_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        drifted_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['DriftStatus'] == 'DRIFTED' and instance['Account'] not in ignore_accounts
        ]
        
        if not drifted_instances:
            return jsonify({'message': 'No drifted instances found.'})
        
        if dry_run:
            return jsonify({'message': 'Dry run: following instances would be retried', 'instances': drifted_instances})
        
        for instance in drifted_instances:
            cloudformation_client.update_stack_instances(
                StackSetName=stack_set_name,
                DeploymentTargets={
                    'Accounts': [instance['Account']],
                    'OrganizationalUnitIds': [instance['OrganizationalUnitId']],
                    'AccountFilterType': 'INTERSECTION',
                },
                Regions=[instance['Region']],
                CallAs='DELEGATED_ADMIN'
            )
        return jsonify({'message': 'Drifted instances retried successfully.', 'instances': drifted_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/get_in_sync_instances', methods=['POST'])
def get_in_sync_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        in_sync_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['DriftStatus'] == 'IN_SYNC' and instance['Account'] not in ignore_accounts
        ]
        
        if not in_sync_instances:
            return jsonify({'message': 'No in sync instances found.'})
        
        return jsonify({'instances': in_sync_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/get_drifted_instances', methods=['POST'])
def get_drifted_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        drifted_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['DriftStatus'] == 'DRIFTED' and instance['Account'] not in ignore_accounts
        ]
        
        if not drifted_instances:
            return jsonify({'message': 'No drifted instances found.'})
        
        return jsonify({'instances': drifted_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/get_succeeded_instances', methods=['POST'])
def get_succeeded_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        succeeded_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SUCCEEDED' and instance['Account'] not in ignore_accounts
        ]
        
        if not succeeded_instances:
            return jsonify({'message': 'No succeeded instances found.'})
        
        return jsonify({'instances': succeeded_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/get_failed_instances', methods=['POST'])
def get_failed_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        failed_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'FAILED' and instance['Account'] not in ignore_accounts
        ]
        
        if not failed_instances:
            return jsonify({'message': 'No failed instances found.'})
        
        return jsonify({'instances': failed_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.route('/get_skipped_suspended_account_instances', methods=['POST'])
def get_skipped_suspended_account_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        skipped_suspended_account_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SKIPPED_SUSPENDED_ACCOUNT' and instance['Account'] not in ignore_accounts
        ]
        
        if not skipped_suspended_account_instances:
            return jsonify({'message': 'No skipped/suspended account instances found.'})
        
        return jsonify({'instances': skipped_suspended_account_instances})
    except Exception as e:
        return jsonify({'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=1980)
