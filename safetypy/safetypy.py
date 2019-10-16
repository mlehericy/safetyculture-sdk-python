# coding=utf-8
# Author: SafetyCulture
# Copyright: © SafetyCulture 2016

import collections
import json
import logging
import os
import re
import sys
import time
import errno
from builtins import input
import requests
from getpass import getpass

DEFAULT_EXPORT_TIMEZONE = 'Etc/UTC'
DEFAULT_EXPORT_FORMAT = 'pdf'
GUID_PATTERN = '[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}$'
HTTP_USER_AGENT_ID = 'safetyculture-python-sdk'

# https://docs.python.org/2.7/howto/logging.html#configuring-logging-for-a-library
try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def handle(self, record):
            pass
        def emit(self, record):
            pass
        def createLock(self):
            self.lock = None
logging.getLogger(__name__).addHandler(logging.NullHandler())


def get_user_api_token(logger):
    """
    Generate iAuditor API Token
    :param logger:  No longer used
    :return:        API Token if authenticated else None
    """
    username = input("iAuditor username: ")
    password = getpass()
    generate_token_url = "https://api.safetyculture.io/auth"
    payload = "username=" + username + "&password=" + password + "&grant_type=password"
    headers = {
        'content-type': "application/x-www-form-urlencoded",
        'cache-control': "no-cache",
    }
    response = requests.request("POST", generate_token_url, data=payload, headers=headers)
    if response.status_code == requests.codes.ok:
        return response.json()['access_token']
    else:
        logging.error('An error occurred calling ' + generate_token_url + ': ' + str(response.json()))
        return None


class SafetyCulture(object):
    def __init__(self, api_token):
        self.current_dir = os.getcwd()
        self.log_dir = self.current_dir + '/log/'
        self.api_url = 'https://api.safetyculture.io/'
        self.audit_url = self.api_url + 'audits/'
        self.template_search_url = self.api_url + 'templates/search?field=template_id&field=name'
        self.response_set_url = self.api_url + 'response_sets'
        self.get_my_groups_url = self.api_url + 'share/connections'
        self.all_groups_url = self.api_url + 'groups'
        self.add_users_url = self.api_url + 'users'

        try:
            token_is_valid = re.match('^[a-f0-9]{64}$', api_token)
            if token_is_valid:
                self.api_token = api_token
            else:
                logging.error('API token failed to match expected pattern')
                self.api_token = None
        except Exception as ex:
            self.log_critical_error(ex, 'API token is missing or invalid. Exiting.')
            exit()
        if self.api_token:
            self.custom_http_headers = {
                'User-Agent': HTTP_USER_AGENT_ID,
                'Authorization': 'Bearer ' + self.api_token
            }
        else:
            logging.error('No valid API token parsed! Exiting.')
            sys.exit(1)

    def authenticated_request_get(self, url):
        return requests.get(url, headers=self.custom_http_headers)

    def authenticated_request_post(self, url, data):
        self.custom_http_headers['content-type'] = 'application/json'
        response = requests.post(url, data, headers=self.custom_http_headers)
        del self.custom_http_headers['content-type']
        return response

    def authenticated_request_put(self, url, data):
        self.custom_http_headers['content-type'] = 'application/json'
        response = requests.put(url, data, headers=self.custom_http_headers)
        del self.custom_http_headers['content-type']
        return response

    def authenticated_request_delete(self, url):
        return requests.delete(url, headers=self.custom_http_headers)

    @staticmethod
    def parse_json(json_to_parse):
        """
        Parse JSON string to OrderedDict and return
        :param json_to_parse:  string representation of JSON
        :return:               OrderedDict representation of JSON
        """
        return json.JSONDecoder(object_pairs_hook=collections.OrderedDict).decode(json_to_parse.decode('utf-8'))

    @staticmethod
    def log_critical_error(ex, message):
        """
        Write exception and description message to log

        :param ex:       Exception instance to log
        :param message:  Descriptive message to describe exception
        """

        logging.critical(message)
        logging.critical(ex)

    def create_directory_if_not_exists(self, path):
        """
        Creates 'path' if it does not exist

        If creation fails, an exception will be thrown

        :param path:    the path to ensure it exists
        """
        try:
            os.makedirs(path)
        except OSError as ex:
            if ex.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                self.log_critical_error(ex, 'An error happened trying to create ' + path)
                raise

    def discover_audits(self, template_id=None, modified_after=None, completed=True):
        """
        Return IDs of all completed audits if no parameters are passed, otherwise restrict search
        based on parameter values
        :param template_id:     Restrict discovery to this template_id
        :param modified_after:  Restrict discovery to audits modified after this UTC timestamp
        :param completed:       Restrict discovery to audits marked as completed, default to True
        :return:                JSON object containing IDs of all audits returned by API
        """

        last_modified = modified_after if modified_after is not None else '2000-01-01T00:00:00.000Z'

        search_url = self.audit_url + 'search?field=audit_id&field=modified_at&order=asc&modified_after=' \
            + last_modified
        log_string = '\nInitiating audit_discovery with the parameters: ' + '\n'
        log_string += 'template_id    = ' + str(template_id) + '\n'
        log_string += 'modified_after = ' + str(last_modified) + '\n'
        log_string += 'completed      = ' + str(completed) + '\n'
        logging.info(log_string)

        if template_id is not None:
            for specific_id in template_id:
                search_url += '&template=' + specific_id
        if completed is True:
            search_url += '&completed=true'
        if completed is False:
            search_url += '&completed=false'
        if completed is 'both':
            search_url += '&completed=both'

        response = self.authenticated_request_get(search_url)
        result = response.json() if response.status_code == requests.codes.ok else None
        number_discovered = str(result['total']) if result is not None else '0'
        log_message = 'on audit_discovery: ' + number_discovered + ' discovered using ' + search_url

        self.log_http_status(response.status_code, log_message)
        return result

    def discover_templates(self, modified_after=None, modified_before=None):
        """
        Query API for all template IDs if no parameters are passed, otherwise restrict search based on parameters

        :param modified_after:   Restrict discovery to templates modified after this UTC timestamp
        :param modified_before:  Restrict discovery to templates modified before this UTC timestamp
        :return:                 JSON object containing IDs of all templates returned by API
        """
        search_url = self.template_search_url
        if modified_before is not None:
            search_url += '&modified_before=' + modified_before
        if modified_after is not None:
            search_url += '&modified_after=' + modified_after

        response = self.authenticated_request_get(search_url)
        result = response.json() if response.status_code == requests.codes.ok else None
        log_message = 'on template discovery using ' + search_url

        self.log_http_status(response.status_code, log_message)
        return result

    def get_export_profile_ids(self, template_id=None):
        """
        Query API for all export profile IDs if no parameters are passed, else restrict to template_id passed
        :param template_id: template_id to obtain export profiles for
        :return:            JSON object containing template name: export profile pairs if no errors, or None
        """
        profile_search_url = self.api_url + 'export_profiles/search'
        if template_id is not None:
            profile_search_url += '?template=' + template_id
        response = self.authenticated_request_get(profile_search_url)
        result = response.json() if response.status_code == requests.codes.ok else None
        return result

    def get_export_profile(self, export_profile_id):
        """
        Query API for export profile corresponding to passed profile_id

        :param export_profile_id:  Export profile ID of the profile to retrieve
        :return:                   Export profile in JSON format
        """
        profile_id_pattern = '^template_[a-fA-F0-9]{32}:' + GUID_PATTERN
        profile_id_is_valid = re.match(profile_id_pattern, export_profile_id)

        if profile_id_is_valid:
            export_profile_url = self.api_url + '/export_profiles/' + export_profile_id
            response = self.authenticated_request_get(export_profile_url)
            result = self.parse_json(response.content) if response.status_code == requests.codes.ok else None
            log_message = 'on export profile retrieval of ' + export_profile_id

            self.log_http_status(response.status_code, log_message)
            return result
        else:
            self.log_critical_error(ValueError,
                                    'export_profile_id {0} does not match expected pattern'.format(export_profile_id))
            return None

    def get_export_job_id(self, audit_id, timezone=DEFAULT_EXPORT_TIMEZONE, export_profile_id=None,
                          export_format=DEFAULT_EXPORT_FORMAT):
        """
        Request export job ID from API and return it

        :param audit_id:           audit_id to retrieve export_job_id for
        :param timezone:           timezone to apply to exports
        :param export_profile_id:  export profile to apply to exports
        :param export_format:      desired format of exported document
        :return:                   export job ID obtained from API
        """
        export_url = self.audit_url + audit_id + '/export?format=' + export_format + '&timezone=' + timezone

        if export_profile_id is not None:
            profile_id_pattern = '^template_[a-fA-F0-9]{32}:' + GUID_PATTERN
            profile_id_is_valid = re.match(profile_id_pattern, export_profile_id)
            if profile_id_is_valid:
                export_url += '&export_profile=' + export_profile_id
            else:
                self.log_critical_error(ValueError,
                                        'export_profile_id {0} does not match expected pattern'.format(
                                            export_profile_id))

        response = self.authenticated_request_post(export_url, data=None)
        result = response.json() if response.status_code == requests.codes.ok else None
        log_message = 'on request to ' + export_url

        self.log_http_status(response.status_code, log_message)
        return result

    def poll_for_export(self, audit_id, export_job_id):
        """
        Poll API for given export job until job is complete or excessive failed attempts occur
        :param audit_id:       audit_id of the export to poll for
        :param export_job_id:  export_job_id of the export to poll for
        :return:               href for export download
        """
        job_id_pattern = '^' + GUID_PATTERN
        job_id_is_valid = re.match(job_id_pattern, export_job_id)

        if job_id_is_valid:
            delay_in_seconds = 5
            poll_url = self.audit_url + audit_id + '/exports/' + export_job_id
            export_attempts = 1
            poll_status = self.authenticated_request_get(poll_url)
            status = poll_status.json()
            if 'status' in status.keys():
                if status['status'] == 'IN PROGRESS':
                    logging.info(str(status['status']) + ' : ' + audit_id)
                    time.sleep(delay_in_seconds)
                    return self.poll_for_export(audit_id, export_job_id)

                elif status['status'] == 'SUCCESS':
                    logging.info(str(status['status']) + ' : ' + audit_id)
                    return status['href']

                else:
                    if export_attempts < 2:
                        export_attempts += 1
                        logging.info('attempt # {0} exporting report for: ' + audit_id.format(str(export_attempts)))
                        retry_id = self.get_export_job_id(audit_id)
                        return self.poll_for_export(audit_id, retry_id['id'])
                    else:
                        logging.error('export for ' + audit_id + ' failed {0} times - skipping'.format(export_attempts))
            else:
                logging.critical('Unexpected response from API: {0}'.format(status))

        else:
            self.log_critical_error(ValueError,
                                    'export_job_id {0} does not match expected pattern'.format(export_job_id))

    def download_export(self, export_href):
        """

        :param export_href:  href for export document to download
        :return:             String representation of exported document
        """

        try:
            response = self.authenticated_request_get(export_href)
            result = response.content if response.status_code == requests.codes.ok else None
            log_message = 'on GET for href: ' + export_href

            self.log_http_status(response.status_code, log_message)
            return result

        except Exception as ex:
            self.log_critical_error(ex, 'Exception occurred while attempting download_export({0})'.format(export_href))

    def get_export(self, audit_id, timezone=DEFAULT_EXPORT_TIMEZONE, export_profile_id=None,
                   export_format=DEFAULT_EXPORT_FORMAT):
        """
        Obtain exported document from API and return string representation of it

        :param audit_id:           audit_id of export to obtain
        :param timezone:           timezone to apply to exports
        :param export_profile_id:  ID of export profile to apply to exports
        :param export_format:      desired format of exported document
        :return:                   String representation of exported document
        """
        export_job_id = self.get_export_job_id(audit_id, timezone, export_profile_id, export_format)['id']
        export_href = self.poll_for_export(audit_id, export_job_id)

        export_content = self.download_export(export_href)
        return export_content

    def get_media(self, audit_id, media_id):
        """
        Get media item associated with a specified audit and media ID
        :param audit_id:    audit ID of document that contains media
        :param media_id:    media ID of image to fetch
        :return:            The Content-Type will be the MIME type associated with the media,
                            and the body of the response is the media itself.
        """
        url = self.audit_url + audit_id + '/media/' + media_id
        response = requests.get(url, headers=self.custom_http_headers, stream=True)
        return response

    def get_web_report(self, audit_id):
        """
        Generate Web Report link associated with a specified audit
        :param audit_id:   Audit ID
        :return:           Web Report link
        """
        url = self.audit_url + audit_id + '/web_report_link'
        response = self.authenticated_request_get(url)
        result = self.parse_json(response.content) if response.status_code == requests.codes.ok else None
        self.log_http_status(response.status_code, 'on GET web report for ' + audit_id)
        if result:
            return result.get('url')
        else:
            return None

    def get_audit_actions(self, date_modified, offset=0, page_length=100):
        """
        Get all actions created after a specified date. If the number of actions found is more than 100, this function will
        page until it has collected all actions

        :param date_modified:   ISO formatted date/time string. Only actions created after this date are are returned.
        :param offset:          The index to start retrieving actions from
        :param page_length:     How many actions to fetch for each page of action results
        :return:                Array of action objects
        """
        actions_url = self.api_url + 'actions/search'
        response = self.authenticated_request_post(
            actions_url,
            data=json.dumps({
                "modified_at": {"from": str(date_modified)},
                "offset": offset,
                "status": [0, 10, 50, 60]
            })
        )
        result = self.parse_json(response.content) if response.status_code == requests.codes.ok else None
        self.log_http_status(response.status_code, 'GET actions')
        if result is None or None in [result.get('count'), result.get('offset'), result.get('total'), result.get('actions')]:
            return None
        return self.get_page_of_actions(date_modified, result, offset, page_length)

    def get_page_of_actions(self, date_modified, previous_page, offset=0, page_length=100):
        """
        Returns a page of action search results

        :param date_modified: fetch from that date onwards
        :param previous_page: a page of action search results
        :param offset: the index to start retrieving actions from
        :param page_length: the number of actions to return on the search page (max 100)
        :return: Array of action objects
        """
        if previous_page['count'] + previous_page['offset'] < previous_page['total']:
            logging.info('Paging Actions. Offset: ' + str(offset + page_length) + '. Total: ' + str(previous_page['total']))
            next_page = self.get_audit_actions(date_modified, offset + page_length)
            if next_page is None:
                return None
            return next_page + previous_page['actions']
        elif previous_page['count'] + previous_page['offset'] == previous_page['total']:
            return previous_page['actions']

    def get_audit(self, audit_id):
        """
        Request JSON representation of a single specified audit and return it

        :param audit_id:  audit_id of document to fetch
        :return:          JSON audit object
        """
        response = self.authenticated_request_get(self.audit_url + audit_id)
        result = self.parse_json(response.content) if response.status_code == requests.codes.ok else None
        log_message = 'on GET for ' + audit_id

        self.log_http_status(response.status_code, log_message)
        return result

    def create_response_set(self, name, responses):
        """
        Create new response_set
        :param payload:  Name and responses of response_set to create
        :return:
        """
        payload = json.dumps({'name': name, 'responses': responses})
        response = self.authenticated_request_post(self.response_set_url, payload)
        log_message = 'on POST for new response_set: {0}'.format(name)
        self.log_http_status(response.status_code, log_message)

    def get_response_sets(self):
        """
        GET and return all response_sets
        :return: response_sets accessible to user
        """
        response = self.authenticated_request_get(self.response_set_url)
        result = self.parse_json(response.content) if response.status_code == requests.codes.ok else None
        log_message = 'on GET for response_sets'
        self.log_http_status(response.status_code, log_message)
        return result

    def get_response_set(self, responseset_id):
        """
        GET individual response_set by id
        :param responseset_id:  responseset_id of response_set to GET
        :return: response_set
        """
        response = self.authenticated_request_get('{0}/{1}'.format(self.response_set_url, responseset_id))
        result = self.parse_json(response.content) if response.status_code == requests.codes.ok else None
        log_message = 'on GET for {0}'.format(responseset_id)
        self.log_http_status(response.status_code, log_message)
        return result

    def create_response(self, responseset_id, response):
        """
        Create response in existing response_set
        :param responseset_id: id of response_set to add response to
        :param response:       response to add
        :return:               None
        """
        url = '{0}/{1}/responses'.format(self.response_set_url, responseset_id)
        response = self.authenticated_request_post(url, json.dumps(response))
        log_message = 'on POST for new response to: {0}'.format(responseset_id)
        self.log_http_status(response.status_code, log_message)

    def delete_response(self, responseset_id, response_id):
        """
        DELETE individual response by id
        :param responseset_id: responseset_id of response_set containing response to be deleted
        :param response_id:    id of response to be deleted
        :return:               None
        """
        url = '{0}/{1}/responses/{2}'.format(self.response_set_url, responseset_id, response_id)
        response = self.authenticated_request_delete(url)
        log_message = 'on DELETE for response_set: {0}'.format(responseset_id)
        self.log_http_status(response.status_code, log_message)

    def get_my_org(self):
        """
        GET the organisation ID of the requesting user
        :return: The organisation ID of the user
        """
        response = self.authenticated_request_get(self.get_my_groups_url)
        log_message = 'on GET for organisations and groups of requesting user'
        self.log_http_status(response.status_code, log_message)
        my_groups_and_orgs = json.loads(response.content)
        org_id = [group['id'] for group in my_groups_and_orgs['groups'] if group['type'] == "organisation"][0]
        return org_id

    def get_all_groups_in_org(self):
        """
        GET all the groups in the requesting user's organisation
        :return: all the groups of the organisation
        """
        response = self.authenticated_request_get(self.all_groups_url)
        log_message = 'on GET for all groups of organisation'
        self.log_http_status(response.status_code, log_message)
        return response if response.status_code == requests.codes.ok else None

    def get_users_of_group(self, group_id):
        """
        GET all the users of the organisations or group
        :param group_id: ID of organisation or group
        :return: array of users
        """
        url = '{0}/{1}/users'.format(self.all_groups_url, group_id)
        response = self.authenticated_request_get(url)
        log_message = 'on GET for users of group: {0}'.format(group_id)
        self.log_http_status(response.status_code, log_message)
        return response.content if response.status_code == requests.codes.ok else None

    def add_user_to_org(self, user_data):
        """
        POST adds a user to organisation
        :param user_data: data of the user to be added
        :return: userID of the user created in the organisation
        """
        url = self.add_users_url
        response = self.authenticated_request_post(url, json.dumps(user_data))
        log_message = 'on POST for adding a user to organisation'
        self.log_http_status(response.status_code, log_message)
        return response.content if response.status_code == requests.codes.ok else None

    def add_user_to_group(self, group_id, user_data):
        """
        POST adds a user to organisation
        :param user_data: contains user ID of user to be added
        :return: userID of the user created in the organisation
        """
        url = '{0}/{1}/users'.format(self.all_groups_url, group_id)
        response = self.authenticated_request_post(url, json.dumps(user_data))
        log_message = 'on POST for adding a user to group'
        self.log_http_status(response.status_code, log_message)
        return response.content if response.status_code == requests.codes.ok else None

    def update_user(self, user_id, user_data):
        """
        PUT updates user details such as user status(active/inactive)
        :param user_id: The ID of the user to update
        :return:  None
        """
        url = '{0}/{1}'.format(self.add_users_url, user_id)
        response = self.authenticated_request_put(url, json.dumps(user_data))
        log_message = 'on PUT for updating a user'
        self.log_http_status(response.status_code, log_message)
        return response if response.status_code == requests.codes.ok else None

    def remove_user(self, role_id, user_id):
        """
        Removes a user from an group/organisation
        :param role_id: The ID of the group or organisation
        :param user_id: The ID of the user to remove
        :return: {ok: true} on successful deletion
        """
        url = '{0}/{1}/users/{2}'.format(self.all_groups_url, role_id, user_id)
        response = self.authenticated_request_delete(url)
        log_message = 'on DELETE for user from group'
        self.log_http_status(response.status_code, log_message)
        return response if response.status_code == requests.codes.ok else None

    @staticmethod
    def log_http_status(status_code, message):
        """
        Write http status code and descriptive message to log

        :param status_code:  http status code to log
        :param message:      to describe where the status code was obtained
        """
        status_description = requests.status_codes._codes[status_code][0]
        log_string = str(status_code) + ' [' + status_description + '] status received ' + message
        logging.info(log_string) if status_code == requests.codes.ok else logging.error(log_string)
