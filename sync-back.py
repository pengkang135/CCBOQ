"""
sync-back.py — Claude Code 配置反向同步到便携仓库
用法:
  python sync-back.py                     # 仅更新模板文件
  python sync-back.py --push              # 更新模板 + 自动提交推送
  python sync-back.py --push -m "说明"    # 自定义 commit message
"""
import json, os, sys, subprocess, argparse
from datetime import datetime

HOME = os.environ['USERPROFILE']
CLAUDE_DIR = HOME + '\\.claude'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def sanitize_paths(obj):
    """替换所有 HOME 路径为 {{HOME}} 占位符"""
    if isinstance(obj, str):
        s = obj.replace(HOME, '{{HOME}}')
        return s.replace(HOME.replace('\\', '/'), '{{HOME}}')
    elif isinstance(obj, dict):
        return {k: sanitize_paths(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_paths(i) for i in obj]
    return obj

def git_run(*args):
    return subprocess.run(['git'] + list(args), cwd=SCRIPT_DIR,
                          capture_output=True, text=True)

def sync():
    print("=" * 50)
    print("  Claude Code 配置反向同步")
    print("=" * 50)
    print()

    # ===== 1. 同步 .claude.json → .claude.json.partial =====
    print("[1/4] 同步 .claude.json → .claude.json.partial")
    claude_json_path = HOME + '\\.claude.json'
    if not os.path.exists(claude_json_path):
        print("  [SKIP] .claude.json 不存在")
    else:
        config = read_json(claude_json_path)
        result = {}

        if 'mcpServers' in config:
            result['mcpServers'] = config['mcpServers']

        if 'projects' in config:
            for key in [HOME, HOME.replace('\\', '/')]:
                if key in config['projects']:
                    proj = config['projects'][key]
                    result['project'] = {
                        'enabledMcpjsonServers': proj.get('enabledMcpjsonServers', []),
                        'disabledMcpjsonServers': proj.get('disabledMcpjsonServers', []),
                        'hasTrustDialogAccepted': proj.get('hasTrustDialogAccepted', True)
                    }
                    break

        write_json(os.path.join(SCRIPT_DIR, '.claude.json.partial'), result)
        print("  [OK] .claude.json.partial")

    # ===== 2. 同步 settings.json → settings.json.template =====
    print("[2/4] 同步 settings.json → settings.json.template")
    settings_path = CLAUDE_DIR + '\\settings.json'
    if not os.path.exists(settings_path):
        print("  [SKIP] settings.json 不存在")
    else:
        settings = read_json(settings_path)
        template = {}

        # 脱敏 env
        env = {}
        for k, v in settings.get('env', {}).items():
            if k == 'ANTHROPIC_AUTH_TOKEN':
                env[k] = '{{ANTHROPIC_AUTH_TOKEN}}'
            elif k == 'ANTHROPIC_BASE_URL':
                env[k] = '{{ANTHROPIC_BASE_URL}}'
            elif k in ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
                        'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL'):
                env[k] = '{{' + k + '}}'
            else:
                env[k] = v
        if env:
            template['env'] = env

        if 'permissions' in settings:
            template['permissions'] = settings['permissions']
        if 'hooks' in settings:
            template['hooks'] = settings['hooks']
        for key in ['language', 'theme', 'effortLevel', 'includeCoAuthoredBy',
                    'skipDangerousModePermissionPrompt', 'enabledPlugins']:
            if key in settings:
                template[key] = settings[key]

        template = sanitize_paths(template)
        write_json(os.path.join(SCRIPT_DIR, 'settings.json.template'), template)
        print("  [OK] settings.json.template")

    # ===== 3. 同步 .mcp.json =====
    print("[3/4] 同步 .mcp.json → .mcp.json")
    mcp_json_path = CLAUDE_DIR + '\\.mcp.json'
    if not os.path.exists(mcp_json_path):
        print("  [SKIP] .mcp.json 不存在")
    else:
        mcp = read_json(mcp_json_path)
        mcp = sanitize_paths(mcp)
        write_json(os.path.join(SCRIPT_DIR, '.mcp.json'), mcp)
        print("  [OK] .mcp.json")

    # ===== 4. 可选: 提交并推送 =====
    print()
    print("[4/4] Git 提交并推送")
    print("  仓库位置: " + SCRIPT_DIR)
    print()

    print("=" * 50)
    print("  同步完成!")
    print("=" * 50)
    print()
    print("已同步的配置:")
    print("  .claude.json.partial   — MCP 服务器定义 (user scope)")
    print("  settings.json.template — 权限 / hooks / 偏好 (已脱敏)")
    print("  .mcp.json              — MCP 会话配置 (已脱敏)")
    print()
    print("运行 python sync-back.py --push 自动提交推送")
    print()

def push(commit_message=None):
    """Git add + commit + push 双 remote"""
    print("[PUSH] 提交并推送到 GitHub + Gitee")

    if not commit_message:
        commit_message = f"sync: 反向同步 Claude Code 配置 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # git add
    r = git_run('add', '.claude.json.partial', 'settings.json.template', '.mcp.json')
    if r.returncode != 0:
        print(f"  git add 失败: {r.stderr}")
        return

    # git status
    r = git_run('status', '--porcelain')
    if not r.stdout.strip():
        print("  没有变更，跳过提交。")
        return

    # git commit
    r = git_run('commit', '-m', commit_message)
    if r.returncode != 0:
        print(f"  git commit 失败: {r.stderr}")
        return
    print(f"  已提交: {commit_message}")

    # git push origin (GitHub)
    r = git_run('push', 'origin', 'master')
    if r.returncode == 0:
        print("  已推送: origin (GitHub)")
    else:
        print(f"  origin 推送失败: {r.stderr.strip()}")

    # git push gitee
    remotes = git_run('remote').stdout.strip().split('\n')
    if 'gitee' in remotes:
        r = git_run('push', 'gitee', 'master')
        if r.returncode == 0:
            print("  已推送: gitee (Gitee)")
        else:
            print(f"  gitee 推送失败: {r.stderr.strip()}")
    else:
        print("  未配置 gitee remote，跳过。")

    print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Claude Code 配置反向同步')
    parser.add_argument('--push', action='store_true', help='自动提交并推送')
    parser.add_argument('-m', '--message', type=str, default=None, help='Commit message')
    args = parser.parse_args()

    sync()
    if args.push:
        push(args.message)
