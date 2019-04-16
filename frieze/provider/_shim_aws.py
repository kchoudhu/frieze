__all__ = ['AwsShim']

import boto3

from openarc.env import getenv

from ._interface import CloudInterface

class AwsShim(CloudInterface):

    def __init__(self, apikey):
        self.api =\
            boto3.client(
                'route53',
                aws_access_key_id=getenv('frieze').extcreds['aws']['apikey'],
                aws_secret_access_key=getenv('frieze').extcreds['aws']['apisecret'],
            )

    def dns_list_zones(self, name=None):
        api_ret = [{
            'vsubid' : hz['Id'],
            'domain' : hz['Name'][:-1],
            'asset'  : hz
        } for hz in self.api.list_hosted_zones()['HostedZones']]

        if name:
            api_ret = [hz for hz in api_ret if hz['domain']==name]

        return api_ret

    def dns_list_records(self, zone, types=[]):
        """EXPLICITLY does not support multiple values for any given record"""
        api_ret = self.api.list_resource_record_sets(HostedZoneId=zone['vsubid'])
        return [{
            'vsubid' : zone['vsubid'],
            'name'   : rr['Name'][:-1],
            'type'   : rr['Type'],
            'value'  : rr['ResourceRecords'][0]['Value'],
            'asset'  : rr
        } for rr in api_ret['ResourceRecordSets'] if (rr['Type'] in types if types else True)]

    def dns_upsert_record(self, vsubid, key, value, ttl=60, type_='A'):
        self.api.change_resource_record_sets(
            HostedZoneId=vsubid,
            ChangeBatch={
                'Changes' : [{
                    'Action' : 'UPSERT',
                    'ResourceRecordSet':{
                        'Name'  : key,
                        'Type'  : type_,
                        'TTL'   : ttl,
                        'ResourceRecords' : [{
                            'Value' : '"%s"' % value if type_=='TXT' else value
                        }]
                    }
                }]
            }
        )
