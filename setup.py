from os.path import abspath, dirname, join

from setuptools import find_packages, setup

this_dir = abspath(dirname(__file__))
with open(join(this_dir, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

about = {}
with open(join(this_dir, 'lsdownloader', '__init__.py'), encoding='utf-8') as f:
    exec(f.read(), about)

setup(
    name='lsdownloader',
    version=about['__version__'],
    description='Search and download Landsat Collection 2 Level 1 product bundles using the USGS/EROS M2M API.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/vudongpham/LandsatDownloader',
    license='MIT',
    keywords='landsat, usgs, m2m, api, download, earth observation, remote sensing, force',
    packages=find_packages(exclude=['tests']),
    install_requires=[
        'requests>=2.25',
        'urllib3>=1.26',
        'tqdm>=4.0',
        'geopandas>=0.12',
    ],
    package_data={'lsdownloader': ['assets/*.gpkg']},
    include_package_data=True,
    python_requires='>=3.9',
    entry_points={
        'console_scripts': [
            'lsdownloader=lsdownloader.cli:main',
        ],
    },
)
