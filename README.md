Frieze
======

Frieze is a python frontend for Ansible that makes orchestrating hardware, services and configuration slightly less maddening by allowing you to gather groups of machines into sites and securely route traffic between them.

##### Preliminaries

Here is a sample Frieze session:

```python
import frieze

# Set domain
domain = frieze.set_domain('anserinae.net')

# Define a new compute node
host = new frieze.host({
    'name' : 'ascendantjustice',
    'type' : 'node'
})

# Define a sitebastion for the site
sitebastion = new frieze.host({
    'name' : 'instatllation01',
    'type' : 'sitebastion'
})

# Create a site definition
site = new frieze.site([sitebastion, host])

# Add some storage
storage = new frieze.host({
    'name' : 'unyieldinghierophant',
    'type' : 'storage'
})

site.add_host(storage)

domain.add_site(site)

domain.deploy()
```

```host```, ```sitebastion``` and ```storage``` are all objects derived from ```FriezeNode```, which encapsulates a machine's hardware, network links, services and certificates.

```site``` is a ```FriezeSite``` object, which represents a set of ```FriezeNodes``` which can talk to each other without any additional routing beyond that provided by the site's ```sitebastion```(see below). ```site```s are grouped together into

```frieze.host()``` can be initiated with any of these types:

* *node*: a compute unit, represented by ```FriezeNode``` and used to host ```FriezeService```-s. Can be either a physical machine or virtual construct (see *hvnode* below).
* *hvnode*: a hypervisor node represented in code by ```FriezeHV```, used to host one or more *node*s.
* *storage*: a node that uses ZFS trickery to store ```site``` state. It is represented in code by objects of type ```FriezeStorage```.
* *sitebastion*: a special node used to route traffic between multiple nodes on the same network. Collectively, a sitebastion and its child nodes form a site. There is precisely one ```sitebastion``` per ```site```.
* *siterouter*: a node used to route traffic between sites. Collectively, a group of sites forms a *domain*.

It is possible to define highly complex topologies using these primitives. An example of what is possible follows.
