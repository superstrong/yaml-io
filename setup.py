import setuptools

setuptools.setup(
    name="yaml_io",
    version="0.1.0",
    author="Robbie Mitchell",
    description="Import and export YAML anchors using custom directives (monkey-patched).",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=["pyyaml>=5.4"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
)
