
/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/
import { assert, bind, each, extend, keys, noop } from 'zrender/lib/core/util.js';
import { initExtentForUnion, isValidBoundsForExtent } from '../util/model.js';
import { getScaleBreakHelper } from './break.js';
import { error } from '../util/log.js';
export var SCALE_EXTENT_KIND_EFFECTIVE = 0;
export var SCALE_EXTENT_KIND_MAPPING = 1;
var SCALE_MAPPER_METHOD_NAMES_MAP = {
  needTransform: 1,
  normalize: 1,
  scale: 1,
  transformIn: 1,
  transformOut: 1,
  contain: 1,
  getExtent: 1,
  getExtentUnsafe: 1,
  setExtent: 1,
  setExtent2: 1,
  getFilter: 1,
  sanitize: 1,
  getDefaultStartValue: 1,
  freeze: 1
};
var SCALE_MAPPER_METHOD_NAMES = keys(SCALE_MAPPER_METHOD_NAMES_MAP);
export var SCALE_MAPPER_DEPTH_OUT_OF_BREAK = 2;
export var SCALE_MAPPER_DEPTH_INNERMOST = 3;
export function initBreakOrLinearMapper(
// If input `null/undefined`, a mapper will be created.
mapper, breakParsed, initialExtent) {
  var brk;
  mapper = mapper || {};
  var scaleBreakHelper = getScaleBreakHelper();
  if (scaleBreakHelper) {
    var brkMapper_1 = scaleBreakHelper.createBreakScaleMapper(breakParsed, initialExtent);
    if (brkMapper_1.hasBreaks()) {
      // Some `ScaleMapper` methods (such as `normalize`) needs to be fast for large data
      // when no breaks, so mount break methods only when breaks really exist.
      each(SCALE_MAPPER_METHOD_NAMES, function (methodName) {
        if (brkMapper_1[methodName]) {
          mapper[methodName] = bind(brkMapper_1[methodName], brkMapper_1);
        }
      });
      brk = brkMapper_1;
    }
  }
  if (brk == null) {
    initLinearScaleMapper(mapper, initialExtent);
  }
  return {
    brk: brk,
    mapper: mapper
  };
}
export function decorateScaleMapper(host, decoratedMapperMethods) {
  each(SCALE_MAPPER_METHOD_NAMES, function (methodName) {
    host[methodName] = decoratedMapperMethods[methodName];
  });
}
export function enableScaleMapperFreeze(host, subMapper) {
  host.freeze = noop;
  if (process.env.NODE_ENV !== 'production') {
    host.freeze = function () {
      subMapper.freeze();
    };
  }
  ;
}
export function getScaleExtentForTickUnsafe(mapper) {
  return mapper.getExtentUnsafe(SCALE_EXTENT_KIND_EFFECTIVE, SCALE_MAPPER_DEPTH_OUT_OF_BREAK);
}
export function getScaleExtentForMappingUnsafe(mapper,
// NullUndefined means the outermost space.
depth) {
  return mapper.getExtentUnsafe(SCALE_EXTENT_KIND_MAPPING, depth) || mapper.getExtentUnsafe(SCALE_EXTENT_KIND_EFFECTIVE, depth);
}
export function getScaleLinearSpanForMapping(mapper) {
  var extent = getScaleExtentForMappingUnsafe(mapper, SCALE_MAPPER_DEPTH_INNERMOST);
  return extent[1] - extent[0];
}
export function getScaleLinearSpanEffective(mapper) {
  var extent = mapper.getExtentUnsafe(SCALE_EXTENT_KIND_EFFECTIVE, SCALE_MAPPER_DEPTH_INNERMOST);
  return extent[1] - extent[0];
}
export function initLinearScaleMapper(
// If input `null/undefined`, a mapper will be created.
mapper, initialExtent) {
  var linearMapper = mapper || {};
  var extendList = [];
  // @ts-ignore
  linearMapper._extents = extendList;
  extendList[SCALE_EXTENT_KIND_EFFECTIVE] = initialExtent ? initialExtent.slice() : initExtentForUnion();
  extend(linearMapper, linearScaleMapperMethods);
  return linearMapper;
}
var linearScaleMapperMethods = {
  needTransform: function () {
    return false;
  },
  normalize: function (val) {
    var extent = this._extents[SCALE_EXTENT_KIND_MAPPING] || this._extents[SCALE_EXTENT_KIND_EFFECTIVE];
    if (extent[1] === extent[0]) {
      return 0.5;
    }
    return (val - extent[0]) / (extent[1] - extent[0]);
  },
  scale: function (val) {
    var extent = this._extents[SCALE_EXTENT_KIND_MAPPING] || this._extents[SCALE_EXTENT_KIND_EFFECTIVE];
    return val * (extent[1] - extent[0]) + extent[0];
  },
  transformIn: function (val) {
    return val;
  },
  transformOut: function (val) {
    return val;
  },
  contain: function (val) {
    // This method is typically used in axis trigger and markers.
    // Users may be confused if the extent is restricted to `SCALE_EXTENT_KIND_EFFECTIVE`.
    var extent = getScaleExtentForMappingUnsafe(this, null);
    return val >= extent[0] && val <= extent[1];
  },
  getExtent: function () {
    return this._extents[SCALE_EXTENT_KIND_EFFECTIVE].slice();
  },
  getExtentUnsafe: function (kind) {
    return this._extents[kind];
  },
  setExtent: function (start, end) {
    if (process.env.NODE_ENV !== 'production') {
      assert(!this._frozen);
    }
    writeExtent(this._extents, SCALE_EXTENT_KIND_EFFECTIVE, start, end);
  },
  setExtent2: function (kind, start, end) {
    if (process.env.NODE_ENV !== 'production') {
      assert(!this._frozen);
    }
    var extentList = this._extents;
    if (!extentList[kind]) {
      extentList[kind] = extentList[SCALE_EXTENT_KIND_EFFECTIVE].slice();
    }
    writeExtent(extentList, kind, start, end);
  },
  freeze: function () {
    if (process.env.NODE_ENV !== 'production') {
      // @ts-ignore
      this._frozen = true;
    }
  }
};
function writeExtent(extentList, kind, start, end) {
  // NOTE: `NaN` should be excluded. e.g., `scaleRawExtentInfo.resultMinMax` may be `[NaN, NaN]`.
  if (isValidBoundsForExtent(start, end)) {
    extentList[kind][0] = start;
    extentList[kind][1] = end;
  } else {
    if (process.env.NODE_ENV !== 'production') {
      // PENDING: should use `assert` after fixing all invalid calls.
      if (start != null && end != null && start <= end) {
        error("Invalid setExtent call - start: " + start + ", end: " + end);
      }
    }
  }
}
// ------ END: Linear Scale Mapper ------