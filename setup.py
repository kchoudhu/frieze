from setuptools import setup

setup(name='frieze',
      version='0.1',
      description='Programmable frontend for Ansible',
      classifiers=[
        'Development Status :: 1 - Planning',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 3.6',
        'Topic :: System :: Clustering',
      ],
      keywords='ansible clusters configuration',
      url='http://github.com/kchoudhu/frieze',
      author='Kamil Choudhury',
      author_email='kamil.choudhury@anserinae.net',
      license='BSD',
      packages=['frieze'],
      install_requires=[
        'openarc',
        'vultr'
      ],
      include_package_data=True,
      zip_safe=False)
