# swift-recycle
Proxy middleware for OpenStack Swift to protect accounts and objects from getting deleted maliciously/accidentally.

This middleware implements a mark-for-deletion mechanism for accounts and objects  as a general safety mechanism 
for the storage layer. There is no special logic for containers, because they cannot be deleted anyway unless they 
are empty (no objects).

## Enabling

Copy `recycle.py` to `/usr/lib/python2.7/dist-packages/swift/common/middleware`, then add a new filter section to
your `proxy-server.conf`:

```
[filter:recycle]
paste.filter_factory = swift.common.middleware.recycle:filter_factory

# Number of seconds after marking an account as deleted (via POST)
# before a DELETE can be issued against it.
account_recycled_seconds = 3600

# Number of seconds after marking an object as deleted (via POST)
# before it will be AUTOMATICALLY expired.
object_recycled_seconds = 3600
```

Add the filter to the `[pipeline:main]` section:

```
[pipeline:main]
pipeline = catch_errors ... <auth middleware> recycle ... proxy-server
```

By placing `recycle` somewhere after auth, you avoid unnecessary
additional auth requests.

## Accounts
Accounts can be marked for deletion by sending `POST` request with a metadata header
`X-Account-Meta-Recycled: yes`. After they are marked, `GET` requests will return a `404 Not Found` error.
A proper `DELETE` request can only be issued after `account_recycled_seconds` have passed.

**Deleting an account:**  
`DELETE`ing an account directly will fail. Instead, we have to mark for deletion
first via `POST` and then `DELETE` after `account_recycled_seconds` has passed.

```
$ curl -v -X POST -H "X-Account-Meta-Recycled: yes" http://1.2.3.4:8080/v1/AUTH_admin
$ curl -v http://1.2.3.4:8080/v1/AUTH_admin
  < HTTP/1.1 404 Not Found
  < X-Account-Meta-Recycled: yes
  < X-Account-Meta-Earliest-Delete-Date: 1570208735
  ...
 Account is marked for deletion. Send X-Remove-Account-Meta-Recycled header via POST to undelete.
```

Then wait `account_recycled_seconds` . . .

```
$ curl -v -X DELETE http://1.2.3.4:8080/v1/AUTH_admin
```

**Undeleting an account:**   
```
$ curl -v -X POST -H "X-Remove-Account-Meta-Recycled: x" http://1.2.3.4:8080/v1/AUTH_admin
$ curl -v http://1.2.3.4:8080/v1/AUTH_admin
  < HTTP/1.1 200 OK
  ...
```

## Objects
Objects can be marked for deletion by sending `POST` request with a metadata header
`X-Object-Meta-Recycled: yes`. After they are marked, `GET` requests will return a `404 Not Found` error.

The `POST` request will internally set the `X-Delete-After` header to `object_recycled_seconds`
and **it will delete the object automatically** after that time.

**Please note:** This is *different* from the account behavior.   
                 No additional `DELETE` request is necessary!

**Deleting an object:**   
Marking an object for deletion via `POST`. They will expire automatically after `object_recycled_seconds`:

```
$ curl -v -X POST -H "X-Object-Meta-Recycled: yes" http://1.2.3.4:8080/v1/AUTH_admin/mycontainer/myobject
$ curl -v http://1.2.3.4:8080/v1/AUTH_admin/mycontainer/myobject
  < HTTP/1.1 404 Not Found
  < X-Object-Meta-Recycled: yes
  < X-Object-Meta-Delete-Date: 1570631037
  ...
  Object is marked for deletion. Send X-Remove-Object-Meta-Recycled header via POST to undelete.
```

Then wait `object_min_recycled_seconds` . . .

```
$ curl -v -X GET http://1.2.3.4:8080/v1/AUTH_admin/mycontainer/myobject
  < HTTP/1.1 404 Not Found
  ...
```

**Undeleting an object** (before `object_min_recycled_seconds` have passed!):   
```
$ curl -v -X POST -H "X-Remove-Object-Meta-Recycled: x" http://1.2.3.4:8080/v1/AUTH_admin/mycontainer/myobject
$ curl -v http://1.2.3.4:8080/v1/AUTH_admin/mycontainer/myobject
  < HTTP/1.1 200 OK
  ...
```

## Recognition & license
This middleware is inspired by the [swift-undelete](https://github.com/swiftstack/swift_undelete) middleware from SwiftStack.  
It is licensed under the Apache License 2.0.
