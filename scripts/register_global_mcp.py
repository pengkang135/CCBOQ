import json

with open('C:/Users/Kevin/.claude.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

HOME = 'C:\\Users\\Kevin'
CLAUDE_DIR = HOME + '\\.claude'

servers = {
    'filesystem': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-filesystem', HOME],
        'env': {}
    },
    'shell': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@wonderwhy-er/desktop-commander'],
        'env': {}
    },
    'git': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '-p', 'github-mcp-server', 'github-mcp-server-mcp'],
        'env': {}
    },
    'http': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mcp-fetch-server'],
        'env': {}
    },
    'mongodb': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mongodb-mcp-server'],
        'env': {'MONGODB_URI': 'mongodb://localhost:27017'}
    },
    'sqlite': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mcp-sqlite', CLAUDE_DIR + '\\data.db'],
        'env': {}
    },
    'excel': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@negokaz/excel-mcp-server'],
        'env': {}
    },
    'playwright': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@playwright/mcp@latest'],
        'env': {}
    },
    'ssh': {
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', 'mcp-server-ssh'],
        'env': {}
    }
}

# 写入顶层 = USER scope (全局)
config['mcpServers'] = servers

with open('C:/Users/Kevin/.claude.json', 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print('Done: 9 MCPs registered at USER scope (global)')
