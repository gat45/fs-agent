"""Tests basiques de l'agent (sans acces reseau)."""
import os
import sys
import tempfile
import shutil
import subprocess

sys.path.insert(0, "E:/agent_fs")
from config import ScanConfig, CompareConfig
from scanner import scan_roots
from agent import FilesystemAgent


def setup_test_data(base):
    a = os.path.join(base, "a")
    b = os.path.join(base, "b")
    os.makedirs(os.path.join(a, "sub"), exist_ok=True)
    os.makedirs(os.path.join(b, "sub"), exist_ok=True)
    # Doublons
    for d, name in [(a, "f1.txt"), (b, "f1_copy.txt")]:
        with open(os.path.join(d, name), "w") as f:
            f.write("hello world")
    # Uniques
    with open(os.path.join(a, "only_a.txt"), "w") as f:
        f.write("unique A")
    with open(os.path.join(b, "only_b.txt"), "w") as f:
        f.write("unique B")
    # Gros fichiers identiques
    big = "x" * 1000
    with open(os.path.join(a, "big.txt"), "w") as f:
        f.write(big)
    with open(os.path.join(b, "big_copy.txt"), "w") as f:
        f.write(big)
    return a, b


def test_scan_and_compare():
    base = tempfile.mkdtemp(dir="E:/temp/opencode")
    try:
        a, b = setup_test_data(base)
        scan_cfg = ScanConfig(roots=[a, b], compute_hash=True, workers=2,
                              output_dir=os.path.join(base, "out"))
        compare_cfg = CompareConfig(by_size=True, by_content=True, by_name=True,
                                     include_unique=True)
        agent = FilesystemAgent(scan_cfg, compare_cfg)
        plan = agent.run()
        assert plan.summary["total_files"] == 6, plan.summary["total_files"]
        assert plan.summary["num_duplicate_groups"] == 2, plan.summary
        assert plan.summary["num_unique_files"] == 2, plan.summary
        assert plan.summary["recoverable_bytes"] == 1011, plan.summary
        print("PASS: test_scan_and_compare")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_no_hash_mode():
    base = tempfile.mkdtemp(dir="E:/temp/opencode")
    try:
        a, b = setup_test_data(base)
        scan_cfg = ScanConfig(roots=[a, b], compute_hash=False, workers=2,
                              output_dir=os.path.join(base, "out"))
        compare_cfg = CompareConfig(by_size=True, by_content=False, by_name=True,
                                     include_unique=True)
        agent = FilesystemAgent(scan_cfg, compare_cfg)
        plan = agent.run()
        assert plan.summary["total_files"] == 6
        # En mode no-hash, pas de doublons de contenu detectes
        assert plan.summary["num_duplicate_groups"] == 0, plan.summary
        print("PASS: test_no_hash_mode")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_excludes():
    base = tempfile.mkdtemp(dir="E:/temp/opencode")
    try:
        a, _ = setup_test_data(base)
        # Creer un fichier dans un dossier exclu
        excl = os.path.join(a, "Windows")
        os.makedirs(excl, exist_ok=True)
        with open(os.path.join(excl, "secret.txt"), "w") as f:
            f.write("secret")
        scan_cfg = ScanConfig(roots=[a], excludes=["Windows"], compute_hash=False,
                              output_dir=os.path.join(base, "out"))
        agent = FilesystemAgent(scan_cfg, CompareConfig())
        plan = agent.run()
        # Le fichier dans Windows ne doit pas etre compte
        all_paths = [f["path"] for f in plan.unique_files]
        for g in plan.duplicate_groups:
            for f in g["files"]:
                all_paths.append(f["path"])
        for p in all_paths:
            assert "Windows" not in p, p
        print("PASS: test_excludes")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_hardlinks():
    base = tempfile.mkdtemp(dir="E:/temp/opencode")
    try:
        a = os.path.join(base, "a")
        os.makedirs(a, exist_ok=True)
        p1 = os.path.join(a, "orig.txt")
        p2 = os.path.join(a, "hard.txt")
        with open(p1, "w") as f:
            f.write("hello hardlink")
        # Creer un hardlink (Windows: mklink /H)
        subprocess.run(["cmd", "/c", "mklink", "/H", p2, p1],
                       capture_output=True, check=False)
        if not os.path.exists(p2):
            print("SKIP: test_hardlinks (mklink non disponible)")
            return
        scan_cfg = ScanConfig(roots=[a], compute_hash=True, workers=2,
                              output_dir=os.path.join(base, "out"))
        agent = FilesystemAgent(scan_cfg, CompareConfig())
        plan = agent.run()
        # Le groupe de doublons doit etre marque comme hardlink
        hl_groups = [g for g in plan.duplicate_groups if g.get("is_hardlink_group")]
        assert len(hl_groups) >= 1, plan.duplicate_groups
        assert hl_groups[0]["wasted_bytes"] == 0
        print("PASS: test_hardlinks")
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    test_scan_and_compare()
    test_no_hash_mode()
    test_excludes()
    test_hardlinks()
    print("ALL TESTS PASSED")
