import sys

# native modules to substititute legacy Django modules
try:
    from hashlib import md5 as md5_constructor
except ImportError:
    from django.utils.hashcompat import md5_constructor

try:
    from itertools import product
except ImportError:
    from django.utils.itercompat import product

# new modules from Django1.4
try:
    from django.utils import timezone
except ImportError:
    timezone = None

try:
    from django.utils.encoding import force_text
except ImportError:
    from django.utils.encoding import force_unicode as force_text

try:
    from django.utils.encoding import smart_text
except ImportError:
    from django.utils.encoding import smart_unicode as smart_text

# new modules from Django1.5
try:
    from django.utils.six import PY3
    _py3 = PY3
except ImportError:
    _py3 = False

try:
    from django.utils.six import b, binary_type, string_types, text_type
except ImportError:
    b = lambda s: s
    binary_type = str
    string_types = basestring
    text_type = unicode

try:
    from django.utils._os import upath
except:
    # derived from Django1.5
    fs_encoding = sys.getfilesystemencoding() or sys.getdefaultencoding()
    def upath(path):
        return path.decode(fs_encoding)

# new modules from Python3
try:
    if _py3:
        from itertools import zip_longest
    else:
        # Python2.6 or 2.7
        from itertools import izip_longest as zip_longest
except ImportError:
    # Python2.5 or earlier
    from itertools import chain, izip, repeat
    # derived from Python2.7 documentation
    def zip_longest(*args, **kwds):
        # izip_longest('ABCD', 'xy', fillvalue='-') --> Ax By C- D-
        fillvalue = kwds.get('fillvalue')
        def sentinel(counter = ([fillvalue]*(len(args)-1)).pop):
            yield counter()         # yields the fillvalue, or raises IndexError
        fillers = repeat(fillvalue)
        iters = [chain(it, sentinel(), fillers) for it in args]
        try:
            for tup in izip(*iters):
                yield tup
        except IndexError:
            pass
