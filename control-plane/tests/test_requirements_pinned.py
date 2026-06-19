import os
import pytest

def test_google_meridian_is_pinned_in_requirements():
    requirements_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../requirements.txt"))
    assert os.path.exists(requirements_path), "requirements.txt does not exist!"
    
    with open(requirements_path, "r") as f:
        lines = f.readlines()
        
    meridian_line = None
    for line in lines:
        cleaned = line.strip()
        if cleaned.startswith("google-meridian"):
            meridian_line = cleaned
            break
            
    assert meridian_line is not None, "google-meridian must be listed in requirements.txt!"
    assert "==" in meridian_line, f"google-meridian must be pinned with '==', but found: {meridian_line}"
    
    version = meridian_line.split("==")[1].strip()
    assert len(version) > 0, "google-meridian version must not be empty!"
    assert version == "1.6.2", f"google-meridian must be pinned to 1.6.2, but found: {version}"
