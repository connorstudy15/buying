"""Enable signed beta access in an existing cloud .env without displaying secrets."""
from pathlib import Path
import os
import shutil


def main():
    path = Path('/home/admin/globex/.env')
    text = path.read_text(encoding='utf-8')
    values = {}
    for line in text.splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    secret = values.get('IDENTITY_HMAC_SECRET', '')
    if len(secret.encode('utf-8')) < 32:
        raise SystemExit('签名密钥缺失或太短，请先完成密钥生成。配置未改变。')
    for key in ('LLM_API_KEY', 'EMBEDDING_API_KEY', 'RERANKER_API_KEY'):
        if not values.get(key) or values[key].startswith('REPLACE_WITH_'):
            raise SystemExit(f'{key} 尚未填写。配置未改变。')
    backup = path.with_name('.env.before-beta-login')
    if not backup.exists():
        shutil.copyfile(path, backup)
        os.chmod(backup, 0o600)
    changes = {'IDENTITY_MODE': 'hmac', 'SESSION_OWNER_BINDING': '1'}
    result = [line for line in text.splitlines()
              if line.split('=', 1)[0].strip() not in changes]
    result.extend(f'{key}={value}' for key, value in changes.items())
    path.write_text('\n'.join(result) + '\n', encoding='utf-8')
    os.chmod(path, 0o600)
    print('配置已切换为签名身份；重建并启动容器后生效。原配置已备份。')


if __name__ == '__main__':
    main()
