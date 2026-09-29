#!/usr/bin/env python3
import argparse
import email.utils
import gzip
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description="Build Debian packages and signed APT metadata from a verified release")
    parser.add_argument("version")
    parser.add_argument("downloads", type=Path)
    parser.add_argument("--revision", default="1")
    parser.add_argument("--gnupghome", type=Path, required=True)
    parser.add_argument("--signing-key", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    downloads = args.downloads.resolve()
    checksums = dict((line.split()[1].lstrip("*"), line.split()[0]) for line in (downloads / "checksums.txt").read_text().splitlines())
    pool = root / "pool/main/a/arcana-world"
    pool.mkdir(parents=True, exist_ok=True)
    version = args.version
    for arch in ("amd64", "arm64"):
        archive = downloads / f"arcana-world-linux-{arch}.tar.gz"
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksums[archive.name]:
            raise ValueError(f"Release checksum mismatch: {archive}")
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp)
            target = package / "usr/lib/arcana-world"
            target.mkdir(parents=True)
            with tarfile.open(archive) as source:
                source.extractall(target, filter="data")
            bindir = package / "usr/bin"
            bindir.mkdir(parents=True)
            (bindir / "arcana-world").symlink_to("../lib/arcana-world/arcana-world")
            docs = package / "usr/share/doc/arcana-world"
            docs.mkdir(parents=True)
            shutil.copy2(target / "LICENSE", docs / "LICENSE")
            (docs / "copyright").write_text(
                "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
                "Upstream-Name: Arcana World\n"
                "Source: https://github.com/TarocchiLive/arcana-world\n\n"
                "Files: *\nCopyright: Arcana World contributors\nLicense: GPL-3.0-only\n"
                " See /usr/share/common-licenses/GPL-3 or the accompanying LICENSE.\n\n"
                "Comment: Corresponding source for this release is available at\n"
                f" https://github.com/TarocchiLive/arcana-world/tree/v{version}\n"
                f" https://github.com/TarocchiLive/arcana-world/archive/refs/tags/v{version}.tar.gz\n"
            )
            control = package / "DEBIAN"
            control.mkdir()
            size = (sum(p.stat().st_size for p in (package / "usr").rglob("*") if p.is_file() and not p.is_symlink()) + 1023) // 1024
            # 发行包 ELF 的最高 GLIBC 符号版本是 2.34；TTS 动态加载 ALSA。
            (control / "control").write_text(
                f"Package: arcana-world\nVersion: {version}-{args.revision}\nArchitecture: {arch}\n"
                "Maintainer: LingLambda <abc1514671906@163.com>\nSection: net\nPriority: optional\n"
                f"Installed-Size: {size}\n"
                "Depends: libc6 (>= 2.34), libwayland-client0, libpangocairo-1.0-0, libpango-1.0-0, libglib2.0-0t64 | libglib2.0-0, libcairo2, libasound2t64 | libasound2, ca-certificates\n"
                "Recommends: fonts-noto-cjk\n"
                "Homepage: https://github.com/TarocchiLive/arcana-world\n"
                "Description: Terminal application for Bilibili live streaming\n"
                " Includes the Wayland overlay and text-to-speech helpers.\n"
                " Overlay requires a compositor supporting wlr-layer-shell.\n"
            )
            run("dpkg-deb", "--root-owner-group", "--build", "-Zxz", str(package), str(pool / f"arcana-world_{version}-{args.revision}_{arch}.deb"))
    suite = root / "dists/stable"
    for arch in ("amd64", "arm64"):
        index = suite / f"main/binary-{arch}"
        index.mkdir(parents=True, exist_ok=True)
        records = []
        for deb in sorted(pool.glob(f"*_{arch}.deb")):
            metadata = run("dpkg-deb", "--field", str(deb), capture_output=True, text=True).stdout
            data = deb.read_bytes()
            records.append(metadata + f"Filename: {deb.relative_to(root)}\nSize: {len(data)}\nSHA256: {hashlib.sha256(data).hexdigest()}\n\n")
        data = "".join(records).encode()
        (index / "Packages").write_bytes(data)
        (index / "Packages.gz").write_bytes(gzip.compress(data, mtime=0))
    release = (
        "Origin: TarocchiLive\nLabel: TarocchiLive\nSuite: stable\nCodename: stable\n"
        f"Date: {email.utils.formatdate(usegmt=True)}\n"
        "Architectures: amd64 arm64\nComponents: main\nDescription: Arcana World official packages\nSHA256:\n"
    )
    for path in sorted(suite.glob("main/binary-*/*")):
        data = path.read_bytes()
        release += f" {hashlib.sha256(data).hexdigest()} {len(data)} {path.relative_to(suite)}\n"
    (suite / "Release").write_text(release)
    gpg = ["gpg", "--homedir", str(args.gnupghome.expanduser()), "--batch", "--yes", "--local-user", args.signing_key]
    run(*gpg, "--clearsign", "--output", str(suite / "InRelease"), str(suite / "Release"))
    run(*gpg, "--armor", "--detach-sign", "--output", str(suite / "Release.gpg"), str(suite / "Release"))
    with (root / "tarocchilive-archive-keyring.gpg").open("wb") as key:
        run(*gpg, "--export", args.signing_key, stdout=key)
    (root / ".nojekyll").touch()


if __name__ == "__main__":
    main()
