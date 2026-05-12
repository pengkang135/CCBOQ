import json
import os

HOME = os.path.expanduser('~')
CLAUDE_DIR = os.path.join(HOME, '.claude')
CLAUDE_JSON = os.path.join(HOME, '.claude.json')

with open(CLAUDE_JSON, 'r', encoding='utf-8') as f:
    config = json.load(f)

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
        'args': ['-y', 'mcp-sqlite', os.path.join(CLAUDE_DIR, 'data.db')],
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

config['mcpServers'] = servers

with open(CLAUDE_JSON, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print('Done: 9 MCPs registered at USER scope (global)')
