import json
import os

import execjs

from app.core.config import BASE_DIR
from app.xhs.services.utils.xhs_util import generate_x_b3_traceid, generate_xray_traceid, splice_str

_STATIC_DIR = str(BASE_DIR / "static")


def _compile_static_js(filename):
    with open(os.path.join(_STATIC_DIR, filename), 'r', encoding='utf-8') as f:
        return execjs.compile(f.read())


_JS_CACHE = {}


def _get_static_js(filename):
    if filename not in _JS_CACHE:
        _JS_CACHE[filename] = _compile_static_js(filename)
    return _JS_CACHE[filename]


def generate_xs(a1, api, data=''):
    ret = _get_static_js('xhs_creator_260411.js').call('get_request_headers_params', api, data, a1)
    xs, xt = ret['xs'], ret['xt']
    if data:
        data = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return xs, xt, data

def generate_xs_xs_common(a1, api, data=''):
    ret = _get_static_js('xhs_creator_260411.js').call('get_request_headers_params', api, data, a1)

    xs, xt, xs_common = ret['xs'], ret['xt'], ret['xs_common']
    return xs, xt, xs_common

def generate_xsc(a1, api, data=''):
    xs, xt, xs_common = generate_xs_xs_common(a1, api, data)
    x_b3_traceid = generate_x_b3_traceid()
    headers = {}
    headers['x-s'] = xs
    headers['x-t'] = str(xt)
    headers['x-s-common'] = xs_common
    headers['x-b3-traceid'] = x_b3_traceid
    headers['x-xray-traceid'] = generate_xray_traceid()
    return headers
