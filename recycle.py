# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""swift-recycle

Proxy middleware for OpenStack Swift to protect accounts and objects from getting deleted maliciously/accidentally.
Detailed instructions: https://github.com/binwiederhier/swift-recycle

"""

from swift.common import swob
from swift.proxy.controllers.base import get_account_info, get_object_info
from time import time

DEFAULT_ACCOUNT_RECYCLED_SECONDS = 2592000 # 30 days
DEFAULT_OBJECT_RECYCLED_SECONDS = 604800 # 7 days

class RecycleMiddleware(object):
    def __init__(self, app,
                 account_recycled_seconds=DEFAULT_ACCOUNT_RECYCLED_SECONDS,
                 object_min_recycled_seconds=DEFAULT_OBJECT_RECYCLED_SECONDS):
        self.app = app
        self.account_recycled_seconds = account_recycled_seconds
        self.object_recycle_keep_seconds = object_min_recycled_seconds

    @swob.wsgify
    def __call__(self, req):
        try:
            vrs, acc, con, obj = req.split_path(2, 4, rest_with_last=True)
        except ValueError:
            return self.app

        # All requests
        if req.method == 'GET':
            account_info = get_account_info(req.environ, self.app)
            if account_info:
                recycled = account_info['meta'].get('recycled', '')
                delete_date = account_info['meta'].get('earliest-delete-date', '')
                if recycled == 'yes' and delete_date != '':
                    return swob.HTTPNotFound(headers={'x-account-meta-recycled': 'yes', 'x-account-meta-earliest-delete-date': delete_date},
                                             body=("Account is marked for deletion. "
                                                   "Send X-Remove-Account-Meta-Recycled header via POST to undelete."))

        # Account specific requests
        if con is None:
            if req.method == 'DELETE':
                account_info = get_account_info(req.environ, self.app)
                if account_info:
                    try:
                        recycled = account_info['meta'].get('recycled', '')
                        delete_date = int(account_info['meta'].get('earliest-delete-date', '0'))

                        if recycled != "yes":
                            return swob.HTTPMethodNotAllowed(content_type="text/plain",
                                                             body=("Account cannot be deleted directly. "
                                                                   "Send 'X-Account-Meta-Recycled: yes' in POST request to mark for deletion.\n"))

                        if time() < delete_date:
                            return swob.HTTPMethodNotAllowed(content_type="text/plain",
                                                             headers={'x-account-meta-recycled': 'yes', 'x-account-meta-earliest-delete-date': delete_date},
                                                             body=("Account cannot be deleted yet, "
                                                                   "X-Account-Meta-Earliest-Delete-Date not reached yet.\n"))
                        return self.app
                    except ValueError:
                        return swob.HTTPInternalError(content_type="text/plain",
                                                      body=("Internal error. Cannot read recycled state.\n"))

            if req.method == 'POST':
                if 'x-account-meta-earliest-delete-date' in req.headers or 'x-remove-account-meta-earliest-delete-date' in req.headers:
                    return swob.HTTPMethodNotAllowed(content_type="text/plain",
                                                     body=("Header X-Account-Meta-Earliest-Delete-Date "
                                                           "cannot be set manually.\n"))

                if 'x-account-meta-recycled' in req.headers and req.headers['x-account-meta-recycled'] == "yes":
                    req.headers['x-account-meta-recycled'] = "yes"
                    req.headers['x-account-meta-earliest-delete-date'] = str(int(time()) + self.account_recycled_seconds)
                    return self.app


                if 'x-remove-account-meta-recycled' in req.headers:
                    req.headers['x-remove-account-meta-recycled'] = "x"
                    req.headers['x-remove-account-meta-earliest-delete-date'] = "x"
                    return self.app

            return self.app

        # Container specific requests
        if obj is None:
            return self.app

        # Object specific requests
        if req.method == 'GET':
            object_info = get_object_info(req.environ, self.app)
            if object_info:
                recycled = object_info['meta'].get('recycled', '')
                delete_date = object_info['meta'].get('delete-date', '')
                if recycled == 'yes':
                    return swob.HTTPNotFound(headers={'x-object-meta-recycled': 'yes', 'x-object-meta-delete-date': delete_date},
                                             body=("Object is marked for deletion. "
                                                   "Send X-Remove-Object-Meta-Recycled header via POST to undelete.\n"))

        if req.method == 'DELETE':
            return swob.HTTPMethodNotAllowed(content_type="text/plain",
                                             body=("DELETE requests are not allowed. "
                                                   "Use POST with 'X-Object-Meta-Recycled: yes' instead.\n"))

        if req.method == 'POST' or req.method == 'PUT':
            if 'x-delete-at' in req.headers or 'x-delete-after' in req.headers or 'x-object-meta-delete-date' in req.headers:
                return swob.HTTPMethodNotAllowed(content_type="text/plain",
                                                 body=("Setting X-Delete-At/X-Delete-After/X-Object-Meta-Delete-Date directly is not allowed. "
                                                       "Use POST with 'X-Object-Meta-Recycled: yes' instead.\n"))

            if 'x-object-meta-recycled' in req.headers:
                if req.headers['x-object-meta-recycled'] != "yes":
                    return swob.HTTPBadRequest(content_type="text/plain",
                                               body=("Invalid value for X-Object-Meta-Recycled. "
                                                     "Only 'yes' is allowed.\n"))

                req.headers['x-object-meta-recycled'] = "yes"
                req.headers['x-object-meta-delete-date'] = str(int(time()) + self.object_recycle_keep_seconds)
                req.headers['x-delete-after'] = str(self.object_recycle_keep_seconds)
                return self.app

            if 'x-remove-object-meta-recycled' in req.headers:
                req.headers['x-remove-object-meta-recycled'] = "x"
                req.headers['x-remove-object-meta-delete-date'] = "x"
                req.headers['x-remove-delete-at'] = "x"
                req.headers['x-remove-delete-after'] = "x"
                return self.app

        return self.app

def filter_factory(global_conf, **local_conf):
    conf = global_conf.copy()
    conf.update(local_conf)

    account_recycled_seconds = int(conf.get("account_recycled_seconds", DEFAULT_ACCOUNT_RECYCLED_SECONDS))
    object_recycled_seconds = int(conf.get("object_recycled_seconds", DEFAULT_OBJECT_RECYCLED_SECONDS))

    def filt(app):
        return RecycleMiddleware(app,
                                 account_recycled_seconds=account_recycled_seconds,
                                 object_min_recycled_seconds=object_recycled_seconds)

    return filt
