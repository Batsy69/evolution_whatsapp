from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

setup(
	name="automate_subcontracting",
	version="1.0.0",
	description="Automate Subcontracting ERPNext",
	author="Rinix Automation Pvt Ltd",
	author_email="admin@rinix.in",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires,
)
