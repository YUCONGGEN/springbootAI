#!/usr/bin/env python3
"""
SBOM (Software Bill of Materials) 生成器

生成 CycloneDX 或 SPDX 格式的软件物料清单，用于生产合规和漏洞追踪。
生成 JSON 格式的 SBOM 文件到 build/sbom.json。
"""

import json
import sys
import os
import importlib.metadata
from datetime import datetime, timezone
from pathlib import Path


def generate_sbom(output_path: str = "build/sbom.json", fmt: str = "cyclonedx"):
    """生成 SBOM"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    components = []
    for dist in importlib.metadata.distributions():
        try:
            name = dist.metadata['Name']
            version = dist.version
            # 跳过egg-info路径导致的重复
            components.append({
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
            })
        except Exception:
            continue

    # 去重
    seen = set()
    unique = []
    for c in components:
        key = (c['name'].lower(), c['version'])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    unique.sort(key=lambda x: x['name'].lower())

    if fmt == "cyclonedx":
        sbom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.4",
            "serialNumber": f"urn:uuid:{_gen_uuid()}",
            "version": 1,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tool": {
                    "vendor": "SpringBootAI",
                    "name": "sbom-generator",
                    "version": "1.0.0"
                },
                "component": {
                    "type": "application",
                    "name": "springbootai",
                    "version": _get_spring_version(),
                }
            },
            "components": [
                {
                    "type": "library",
                    "name": c["name"],
                    "version": c["version"],
                    "purl": c["purl"],
                }
                for c in unique
            ],
        }
    else:
        # Simple SPDX-like JSON
        sbom = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "springbootai-sbom",
            "documentNamespace": f"https://springbootai.io/spdx/{_gen_uuid()}",
            "creationInfo": {
                "created": datetime.now(timezone.utc).isoformat(),
                "creators": ["Tool: SpringBootAI-SBOM-Generator-1.0.0"],
            },
            "packages": [
                {
                    "SPDXID": f"SPDXRef-Package-{i}",
                    "name": c["name"],
                    "versionInfo": c["version"],
                    "primaryPackagePurpose": "LIBRARY",
                }
                for i, c in enumerate(unique)
            ],
        }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(sbom, f, indent=2, ensure_ascii=False)

    print(f"SBOM generated: {output_path}")
    print(f"Total components: {len(unique)}")
    return sbom


def _gen_uuid():
    """简单UUID生成（不依赖uuid模块以避免在最小环境报错）"""
    import random
    hex_chars = '0123456789abcdef'
    return ''.join(random.choice(hex_chars) for _ in range(8)) + '-' + \
           ''.join(random.choice(hex_chars) for _ in range(4)) + '-4' + \
           ''.join(random.choice(hex_chars) for _ in range(3)) + '-' + \
           random.choice('89ab') + ''.join(random.choice(hex_chars) for _ in range(3)) + '-' + \
           ''.join(random.choice(hex_chars) for _ in range(12))


def _get_spring_version():
    """获取SpringBootAI版本"""
    try:
        init_py = Path(__file__).parent.parent / "spring" / "__init__.py"
        for line in init_py.read_text().splitlines():
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip("'\"")
    except Exception:
        pass
    return "unknown"


def generate_lock_file(requirements_file: str = "requirements.txt",
                       lock_file: str = "requirements-lock.txt"):
    """
    生成锁定版本文件，包含所有传递依赖的精确版本。
    使用 pip freeze 生成完整依赖树。
    """
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'freeze', '--all'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            # 过滤掉pip/setuptools/wheel本身
            exclude = {'pip', 'setuptools', 'wheel'}
            filtered = [l for l in lines if l.split('==')[0].lower() not in exclude
                        and '==' in l and not l.startswith('-e')]
            filtered.sort(key=lambda x: x.split('==')[0].lower())

            with open(lock_file, 'w', encoding='utf-8') as f:
                f.write("# Auto-generated lock file - DO NOT EDIT\n")
                f.write(f"# Generated at: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"# Python: {sys.version}\n")
                f.write("# Run: pip install -r requirements-lock.txt for reproducible builds\n\n")
                for line in filtered:
                    f.write(line + '\n')
            print(f"Lock file generated: {lock_file} ({len(filtered)} packages)")
            return True
    except Exception as e:
        print(f"Failed to generate lock file: {e}", file=sys.stderr)
    return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate SBOM and lock files')
    parser.add_argument('--sbom-only', action='store_true', help='Only generate SBOM')
    parser.add_argument('--lock-only', action='store_true', help='Only generate lock file')
    parser.add_argument('--output', default='build/sbom.json', help='SBOM output path')
    parser.add_argument('--lock', default='requirements-lock.txt', help='Lock file path')
    args = parser.parse_args()

    if not args.lock_only:
        generate_sbom(args.output)
    if not args.sbom_only:
        generate_lock_file(lock_file=args.lock)
