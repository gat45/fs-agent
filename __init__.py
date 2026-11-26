"""Agent de scan et comparaison de systeme de fichiers multi-disques."""
__version__ = "1.0.0"
from agent import FilesystemAgent
from config import ScanConfig, CompareConfig
__all__ = ["FilesystemAgent", "ScanConfig", "CompareConfig"]
