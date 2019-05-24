from setuptools import setup, find_packages

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
      packages=find_packages(),
      package_data={'frieze' : ['capability/resources/*/*']},
      install_requires=[
        'bless',
        'boto3',
        'certbot',
        'cryptography',
        'mako',
        'openarc',
        'vultr'
      ],
      zip_safe=False)
