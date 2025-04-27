from flask import Flask, render_template, jsonify, request
import boto3
import os
import functools
import logging
import datetime

app = Flask(__name__)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 获取环境变量中的AWS身份信息和区域信息
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
aws_session_token = os.getenv('AWS_SESSION_TOKEN')
aws_region = os.getenv('AWS_DEFAULT_REGION')

logger.info(f"启动应用，使用区域: {aws_region}")

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
    logger.info("获取组织账户列表")
    accounts = []
    paginator = organizations_client.get_paginator('list_accounts')
    for page in paginator.paginate():
        accounts.extend(page['Accounts'])
    logger.info(f"获取到 {len(accounts)} 个组织账户")
    return accounts

@app.route('/get_organization_accounts', methods=['GET'])
def get_organization_accounts_route():
    try:
        logger.info("处理请求: 获取组织账户列表")
        accounts = get_organization_accounts()
        accounts.sort(key=lambda x: x['Name'])  # 按名称排序
        logger.info(f"成功返回 {len(accounts)} 个账户信息")
        return jsonify(accounts)
    except Exception as e:
        logger.error(f"获取组织账户时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@functools.lru_cache(maxsize=128)
def get_stack_instances(stack_set_name):
    logger.info(f"获取StackSet实例: {stack_set_name}")
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
    logger.info(f"获取到 {len(instances)} 个StackSet实例")
    return instances

@app.route('/')
def list_stacksets():
    try:
        logger.info("处理请求: 列出所有StackSets")
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

        logger.info(f"获取到 {len(stack_sets)} 个StackSets")
        
        # 获取组织中的所有账户
        organization_accounts = get_organization_accounts()
        total_organization_accounts = len(organization_accounts)
        
        # 获取所有StackSet的详细信息
        stack_set_details_list = []
        for stack_set in stack_sets:
            stack_set_name = stack_set['StackSetName']
            logger.info(f"获取StackSet详情: {stack_set_name}")
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
            
            logger.info(f"StackSet {stack_set_name} 统计: 总实例={total_instances}, 同步={in_sync}, 偏差={drifted}, "
                      f"成功={succeeded}, 失败={failed}, 跳过账户={skipped_suspended_account}, 未部署账户={len(not_deployed_accounts)}")
            
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
        
        logger.info("成功渲染StackSets列表页面")
        return render_template('list_stacksets.html', stack_set_details_list=stack_set_details_list)
    except Exception as e:
        logger.error(f"列出StackSets时出错: {str(e)}", exc_info=True)
        return f"An error occurred: {str(e)}"

@app.route('/add_undeployed_accounts', methods=['POST'])
def add_undeployed_accounts():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 添加未部署账户到StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}, 干运行: {dry_run}")
    
    try:
        # Retrieve organization accounts
        organization_accounts = get_organization_accounts()
        organization_account_ids = {account['Id'] for account in organization_accounts}

        # Retrieve root OU ID
        root_ou_id = get_organization_root_ou_id()
        logger.info(f"获取组织根OU ID: {root_ou_id}")

        # List stack instances to get deployed accounts
        instances = get_stack_instances(stack_set_name)
        deployed_account_ids = {instance['Account'] for instance in instances}

        # Calculate undeployed account IDs
        undeployed_account_ids = organization_account_ids - deployed_account_ids - ignore_accounts
        undeployed_account_details = [account for account in organization_accounts if account['Id'] in undeployed_account_ids]
        
        logger.info(f"未部署账户数: {len(undeployed_account_details)}")
        
        # Dry run response
        if dry_run:
            logger.info(f"干运行结束，发现 {len(undeployed_account_details)} 个未部署账户")
            return jsonify({'message': 'Dry run: following accounts would be added', 'accounts': undeployed_account_details})
        
        # Add undeployed accounts
        for account in undeployed_account_details:
            logger.info(f"添加账户 {account['Id']} ({account['Name']}) 到 StackSet {stack_set_name}")
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
        
        logger.info(f"成功添加 {len(undeployed_account_details)} 个未部署账户到 StackSet {stack_set_name}")
        return jsonify({'message': 'Undeployed accounts added successfully.', 'accounts': undeployed_account_details})
    except Exception as e:
        logger.error(f"添加未部署账户时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

def get_organization_root_ou_id():
    try:
        logger.info("获取组织根OU ID")
        response = organizations_client.list_roots()
        root_ou_id = response['Roots'][0]['Id']
        return root_ou_id
    except Exception as e:
        logger.error(f"获取组织根OU ID时出错: {str(e)}", exc_info=True)
        raise Exception(f"Failed to retrieve organization root OU ID: {str(e)}")

@app.route('/remove_suspended_accounts', methods=['POST'])
def remove_suspended_accounts():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 移除暂停账户从StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}, 干运行: {dry_run}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        outdated_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SKIPPED_SUSPENDED_ACCOUNT' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(outdated_instances)} 个潜在的暂停账户实例")
        
        account_statuses = {}
        for instance in outdated_instances[:]:
            account_id = instance['Account']
            if account_id in ignore_accounts:
                continue
            try:
                account_status = organizations_client.describe_account(AccountId=account_id)['Account']['Status']
                logger.info(f"账户 {account_id} 状态: {account_status}")
                if account_status != 'SUSPENDED':
                    outdated_instances.remove(instance)
            except Exception as e:
                logger.warning(f"无法获取账户 {account_id} 状态，可能已被删除: {str(e)}")
                account_status = 'Deleted'
            account_statuses[account_id] = account_status
        
        if not outdated_instances:
            logger.info("未找到暂停账户")
            return jsonify({'message': 'No suspended accounts found.'})
        
        # Combine instances with the same OrganizationalUnitId and Region
        combined_instances = {}
        for instance in outdated_instances:
            key = (instance['OrganizationalUnitId'], instance['Region'])
            instance['Status']=account_statuses[instance['Account']]
            if key not in combined_instances:
                combined_instances[key] = []
            combined_instances[key].append(instance)
        
        logger.info(f"将移除 {len(outdated_instances)} 个暂停账户实例")
        
        for (ou_id, region), accounts in combined_instances.items():
            if dry_run:
                logger.info(f"干运行结束，发现 {len(accounts)} 个要移除的暂停账户")
                return jsonify({'message': 'Dry run: following accounts would be removed', 'accounts': accounts})
            else:
                logger.info(f"移除 {len(accounts)} 个暂停账户从OU {ou_id}, 区域 {region}")
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
        
                logger.info(f"成功移除暂停账户")
                return jsonify({'message': 'Suspended accounts removed successfully.'})
    except Exception as e:
        logger.error(f"移除暂停账户时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/retry_failed_instances', methods=['POST'])
def retry_failed_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 重试失败实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}, 干运行: {dry_run}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        failed_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'FAILED' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(failed_instances)} 个失败实例")
        
        if not failed_instances:
            logger.info("未找到失败实例")
            return jsonify({'message': 'No failed instances found.'})
        
        if dry_run:
            logger.info(f"干运行结束，发现 {len(failed_instances)} 个要重试的失败实例")
            return jsonify({'message': 'Dry run: following instances would be retried', 'instances': failed_instances})
        
        for instance in failed_instances:
            logger.info(f"重试失败实例: 账户 {instance['Account']}, 区域 {instance['Region']}")
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
        logger.info(f"已成功重试 {len(failed_instances)} 个失败实例")
        return jsonify({'message': 'Failed instances retried successfully.', 'instances': failed_instances})
    except Exception as e:
        logger.error(f"重试失败实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/retry_drifted_instances', methods=['POST'])
def retry_drifted_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    dry_run = data.get('dryRun', False)
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 重试偏差实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}, 干运行: {dry_run}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        drifted_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['DriftStatus'] == 'DRIFTED' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(drifted_instances)} 个偏差实例")
        
        if not drifted_instances:
            logger.info("未找到偏差实例")
            return jsonify({'message': 'No drifted instances found.'})
        
        if dry_run:
            logger.info(f"干运行结束，发现 {len(drifted_instances)} 个要重试的偏差实例")
            return jsonify({'message': 'Dry run: following instances would be retried', 'instances': drifted_instances})
        
        for instance in drifted_instances:
            logger.info(f"重试偏差实例: 账户 {instance['Account']}, 区域 {instance['Region']}")
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
        logger.info(f"已成功重试 {len(drifted_instances)} 个偏差实例")
        return jsonify({'message': 'Drifted instances retried successfully.', 'instances': drifted_instances})
    except Exception as e:
        logger.error(f"重试偏差实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/get_in_sync_instances', methods=['POST'])
def get_in_sync_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 获取同步实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        in_sync_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['DriftStatus'] == 'IN_SYNC' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(in_sync_instances)} 个同步实例")
        
        if not in_sync_instances:
            logger.info("未找到同步实例")
            return jsonify({'message': 'No in sync instances found.'})
        
        return jsonify({'instances': in_sync_instances})
    except Exception as e:
        logger.error(f"获取同步实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/get_drifted_instances', methods=['POST'])
def get_drifted_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 获取偏差实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        drifted_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['DriftStatus'] == 'DRIFTED' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(drifted_instances)} 个偏差实例")
        
        if not drifted_instances:
            logger.info("未找到偏差实例")
            return jsonify({'message': 'No drifted instances found.'})
        
        return jsonify({'instances': drifted_instances})
    except Exception as e:
        logger.error(f"获取偏差实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/get_succeeded_instances', methods=['POST'])
def get_succeeded_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 获取成功实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        succeeded_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SUCCEEDED' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(succeeded_instances)} 个成功实例")
        
        if not succeeded_instances:
            logger.info("未找到成功实例")
            return jsonify({'message': 'No succeeded instances found.'})
        
        return jsonify({'instances': succeeded_instances})
    except Exception as e:
        logger.error(f"获取成功实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/get_failed_instances', methods=['POST'])
def get_failed_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 获取失败实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        failed_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'FAILED' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(failed_instances)} 个失败实例")
        
        if not failed_instances:
            logger.info("未找到失败实例")
            return jsonify({'message': 'No failed instances found.'})
        
        return jsonify({'instances': failed_instances})
    except Exception as e:
        logger.error(f"获取失败实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

@app.route('/get_skipped_suspended_account_instances', methods=['POST'])
def get_skipped_suspended_account_instances():
    data = request.get_json()
    stack_set_name = data['stackSetName']
    ignore_accounts = set(data.get('ignoreAccounts', []))
    
    logger.info(f"处理请求: 获取跳过/暂停账户实例 StackSet {stack_set_name}, 忽略账户数: {len(ignore_accounts)}")
    
    try:
        instances = get_stack_instances(stack_set_name)
        
        skipped_suspended_account_instances = [
            {'Account': instance['Account'], 'Region': instance['Region'], 'OrganizationalUnitId': instance['OrganizationalUnitId']}
            for instance in instances if instance['StackInstanceStatus']['DetailedStatus'] == 'SKIPPED_SUSPENDED_ACCOUNT' and instance['Account'] not in ignore_accounts
        ]
        
        logger.info(f"发现 {len(skipped_suspended_account_instances)} 个跳过/暂停账户实例")
        
        if not skipped_suspended_account_instances:
            logger.info("未找到跳过/暂停账户实例")
            return jsonify({'message': 'No skipped/suspended account instances found.'})
        
        return jsonify({'instances': skipped_suspended_account_instances})
    except Exception as e:
        logger.error(f"获取跳过/暂停账户实例时出错: {str(e)}", exc_info=True)
        return jsonify({'message': str(e)}), 500

if __name__ == '__main__':
    start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"应用启动时间: {start_time}")
    app.run(debug=False, host='0.0.0.0', port=1980)
