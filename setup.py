from setuptools import setup, find_packages

setup(
    name="agentp",
    version="1.0.3",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "agentp=agentp.main:main",
        ],
    },
)