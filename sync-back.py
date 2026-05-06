"""
sync-back.py -- Claude Code 全量配置反向同步到便携仓库
用法:
  python sync-back.py                     # 仅更新配置
  python sync-back.py --push              # 更新 + 自动提交推送
  python sync-back.py --push -m "说明"    # 自定义 commit message
"""
import json, os, sys, subprocess, argparse, shutil
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

def copy_file(src, dst):
    """复制单个文件"""
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True
    return False

def copy_dir(src_dir, dst_dir, exclude_dirs=None, exclude_patterns=None):
    """复制目录，可排除子目录"""
    if not os.path.exists(src_dir):
        return 0
    if exclude_dirs is None:
        exclude_dirs = {'.git', '__pycache__', '.venv', 'node_modules', 'venv'}
    if exclude_patterns is None:
        exclude_patterns = []
    os.makedirs(dst_dir, exist_ok=True)
    count = 0
    for item in os.listdir(src_dir):
        if item in exclude_dirs:
            continue
        src_path = os.path.join(src_dir, item)
        dst_path = os.path.join(dst_dir, item)
        if os.path.isfile(src_path):
            skip = False
            for pat in exclude_patterns:
                if pat in item:
                    skip = True
                    break
            if not skip:
                shutil.copy2(src_path, dst_path)
                count += 1
        elif os.path.isdir(src_path):
            c = copy_dir(src_path, dst_path, exclude_dirs, exclude_patterns)
            count += c
    return count

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
    print("  Claude Code 全量配置反向同步")
    print("=" * 50)
    print()

    # ===== 1. .claude.json → .claude.json.partial =====
    print("[1/8] 同步 .claude.json → .claude.json.partial")
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

    # ===== 2. settings.json → settings.json.template =====
    print("[2/8] 同步 settings.json → settings.json.template")
    settings_path = CLAUDE_DIR + '\\settings.json'
    if not os.path.exists(settings_path):
        print("  [SKIP] settings.json 不存在")
    else:
        settings = read_json(settings_path)
        template = {}

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
            template['permissions'] = sanitize_paths(settings['permissions'])
        if 'hooks' in settings:
            template['hooks'] = sanitize_paths(settings['hooks'])
        for key in ['language', 'theme', 'effortLevel', 'includeCoAuthoredBy',
                    'skipDangerousModePermissionPrompt', 'enabledPlugins']:
            if key in settings:
                template[key] = settings[key]

        write_json(os.path.join(SCRIPT_DIR, 'settings.json.template'), template)
        print("  [OK] settings.json.template")

    # ===== 3. .mcp.json → .mcp.json (sanitized) =====
    print("[3/8] 同步 .mcp.json")
    mcp_json_path = CLAUDE_DIR + '\\.mcp.json'
    if not os.path.exists(mcp_json_path):
        print("  [SKIP] .mcp.json 不存在")
    else:
        mcp = read_json(mcp_json_path)
        mcp = sanitize_paths(mcp)
        write_json(os.path.join(SCRIPT_DIR, '.mcp.json'), mcp)
        print("  [OK] .mcp.json")

    # ===== 4. CLAUDE.md =====
    print("[4/8] 同步 CLAUDE.md")
    if copy_file(CLAUDE_DIR + '\\CLAUDE.md', SCRIPT_DIR + '\\CLAUDE.md'):
        print("  [OK] CLAUDE.md")
    else:
        print("  [SKIP] CLAUDE.md 不存在")

    # ===== 5. auto-approve-safe-tools.ps1 =====
    print("[5/8] 同步 auto-approve-safe-tools.ps1")
    if copy_file(CLAUDE_DIR + '\\auto-approve-safe-tools.ps1',
                 SCRIPT_DIR + '\\auto-approve-safe-tools.ps1'):
        print("  [OK] auto-approve-safe-tools.ps1")
    else:
        print("  [SKIP] auto-approve-safe-tools.ps1 不存在")

    # ===== 6. scripts/, skills/, plugins/, mcp-servers/, sounds/ =====
    dirs_to_sync = ['scripts', 'skills', 'sounds']
    exclude_dirs = {'.git', '__pycache__', '.venv', 'node_modules', 'venv'}

    for dirname in dirs_to_sync:
        n = 6 + dirs_to_sync.index(dirname)
        print(f"[{n}/8] 同步 {dirname}/")
        src = CLAUDE_DIR + '\\' + dirname
        dst = SCRIPT_DIR + '\\' + dirname
        count = copy_dir(src, dst, exclude_dirs)
        print(f"  [OK] {dirname}/ ({count} 个文件)")

    # plugins/ — 只同步配置 JSON，不同步缓存
    print("[7/8] 同步 plugins/ 配置")
    plugins_src = CLAUDE_DIR + '\\plugins'
    plugins_dst = SCRIPT_DIR + '\\plugins'
    os.makedirs(plugins_dst, exist_ok=True)
    for fname in ['installed_plugins.json', 'known_marketplaces.json']:
        if copy_file(os.path.join(plugins_src, fname), os.path.join(plugins_dst, fname)):
            print(f"  [OK] plugins/{fname}")
        else:
            print(f"  [SKIP] plugins/{fname} 不存在")

    # mcp-servers/ — 排除 .venv 和 node_modules
    print("[8/8] 同步 mcp-servers/")
    mcp_src = CLAUDE_DIR + '\\mcp-servers'
    mcp_dst = SCRIPT_DIR + '\\mcp-servers'
    count = copy_dir(mcp_src, mcp_dst, {'.git', '__pycache__', '.venv', 'node_modules', 'venv'})
    print(f"  [OK] mcp-servers/ ({count} 个文件)")

    # settings.local.json
    if copy_file(CLAUDE_DIR + '\\settings.local.json', SCRIPT_DIR + '\\settings.local.json'):
        print("  [OK] settings.local.json")

    print()
    print("=" * 50)
    print("  同步完成!")
    print("=" * 50)
    print()
    print("运行 python sync-back.py --push 自动提交推送")
    print()

def push(commit_message=None):
    """Git add + commit + push 双 remote"""
    print("[PUSH] 提交并推送到 GitHub + Gitee")

    if not commit_message:
        commit_message = f"sync: 反向同步 Claude Code 全量配置 {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    tracked_files = [
        '.claude.json.partial', 'settings.json.template', '.mcp.json',
        'CLAUDE.md', 'auto-approve-safe-tools.ps1', 'settings.local.json'
    ]
    tracked_dirs = ['scripts', 'skills', 'plugins', 'mcp-servers', 'sounds']

    for f in tracked_files:
        path = os.path.join(SCRIPT_DIR, f)
        if os.path.exists(path):
            git_run('add', f)

    for d in tracked_dirs:
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.exists(path):
            git_run('add', d)

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
    parser = argparse.ArgumentParser(description='Claude Code 全量配置反向同步')
    parser.add_argument('--push', action='store_true', help='自动提交并推送')
    parser.add_argument('-m', '--message', type=str, default=None, help='Commit message')
    args = parser.parse_args()

    sync()
    if args.push:
        push(args.message)
