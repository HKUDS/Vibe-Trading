
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
import { __extends } from "tslib";
import Scale from './Scale.js';
import IntervalScale from './Interval.js';
import { logScalePowTick, logScaleLogTick } from './helper.js';
import { getBreaksUnsafe, getScaleBreakHelper } from './break.js';
import { getMinorTicks } from './minorTicks.js';
import { decorateScaleMapper, enableScaleMapperFreeze, SCALE_EXTENT_KIND_EFFECTIVE, SCALE_MAPPER_DEPTH_OUT_OF_BREAK } from './scaleMapper.js';
import { map } from 'zrender/lib/core/util.js';
import { isValidBoundsForExtent } from '../util/model.js';
import { isNullableNumberFinite } from '../util/number.js';
var LOOKUP_IDX_EXTENT_START = 0;
var LOOKUP_IDX_EXTENT_END = 1;
var LOOKUP_IDX_BREAK_START = 2;
/**
 * @final NEVER inherit me!
 */
var LogScale = /** @class */function (_super) {
  __extends(LogScale, _super);
  function LogScale(setting) {
    var _this = _super.call(this) || this;
    _this.type = 'log';
    _this.parse = IntervalScale.parse;
    _this.base = setting.logBase || 10;
    var lookupFrom = [];
    var lookupTo = [];
    var lookup = _this._lookup = {
      from: lookupFrom,
      to: lookupTo
    };
    lookupFrom[LOOKUP_IDX_EXTENT_START] = lookupFrom[LOOKUP_IDX_EXTENT_END] = lookupTo[LOOKUP_IDX_EXTENT_START] = lookupTo[LOOKUP_IDX_EXTENT_END] = NaN;
    decorateScaleMapper(_this, LogScale.mapperMethods);
    var scaleBreakHelper = getScaleBreakHelper();
    var breakOption = setting.breakOption;
    var out = {
      lookup: lookup
    };
    if (scaleBreakHelper) {
      scaleBreakHelper.parseAxisBreakOptionInwardTransform(breakOption, _this, {
        noNegative: true
      }, LOOKUP_IDX_BREAK_START, out);
    }
    _this.powStub = new IntervalScale({
      breakParsed: out.original
    });
    _this.intervalStub = new IntervalScale({
      breakParsed: out.transformed
    });
    enableScaleMapperFreeze(_this, _this.intervalStub);
    return _this;
  }
  LogScale.prototype.getTicks = function (opt) {
    var base = this.base;
    var powStub = this.powStub;
    var scaleBreakHelper = getScaleBreakHelper();
    var intervalStub = this.intervalStub;
    var intervalExtent = intervalStub.getExtent();
    var powExtent = powStub.getExtent();
    var powOpt = {
      lookup: {
        from: intervalExtent,
        to: powExtent
      }
    };
    return map(intervalStub.getTicks(opt || {}), function (tick) {
      var val = tick.value;
      var powVal = logScalePowTick(val, base, powOpt);
      var vBreak;
      if (scaleBreakHelper) {
        var brkPowResult = scaleBreakHelper.getTicksBreakOutwardTransform(this, tick, getBreaksUnsafe(powStub), this._lookup);
        if (brkPowResult) {
          vBreak = brkPowResult.vBreak;
          powVal = brkPowResult.tickVal;
        }
      }
      return {
        value: powVal,
        "break": vBreak
      };
    }, this);
  };
  LogScale.prototype.getMinorTicks = function (splitNumber) {
    return getMinorTicks(this, splitNumber, getBreaksUnsafe(this.powStub),
    // NOTE: minor ticks are in the log scale value to visually hint users "logarithm".
    this.intervalStub.getConfig().interval);
  };
  LogScale.prototype.getLabel = function (data, opt) {
    return this.intervalStub.getLabel(data, opt);
  };
  LogScale.type = 'log';
  LogScale.mapperMethods = {
    needTransform: function () {
      return true;
    },
    normalize: function (val) {
      return this.intervalStub.normalize(logScaleLogTick(val, this.base));
    },
    scale: function (val) {
      // PENDING: Input `intervalStub.getExtent()` and `powStub.getExtent()` may
      // break monotonicity. Do not do it until real problems found.
      return logScalePowTick(this.intervalStub.scale(val), this.base, null);
    },
    transformIn: function (val, opt) {
      val = logScaleLogTick(val, this.base);
      return opt && opt.depth === SCALE_MAPPER_DEPTH_OUT_OF_BREAK ? val : this.intervalStub.transformIn(val, opt);
    },
    transformOut: function (val, opt) {
      var depth = opt ? opt.depth : null;
      tmpTransformOutOpt1.depth = depth;
      tmpTransformOutOpt2.lookup = this._lookup;
      return logScalePowTick(depth === SCALE_MAPPER_DEPTH_OUT_OF_BREAK ? val : this.intervalStub.transformOut(val, tmpTransformOutOpt1), this.base, tmpTransformOutOpt2);
    },
    contain: function (val) {
      return this.powStub.contain(val);
    },
    /**
     * NOTICE: The caller should ensure `start` and `end` are both non-negative.
     */
    setExtent: function (start, end) {
      this.setExtent2(SCALE_EXTENT_KIND_EFFECTIVE, start, end);
    },
    setExtent2: function (kind, start, end) {
      if (!isValidBoundsForExtent(start, end) || start <= 0 || end <= 0) {
        return;
      }
      var lookupTo = tmpNotUsedArr;
      var lookupFrom = tmpNotUsedArr;
      if (kind === SCALE_EXTENT_KIND_EFFECTIVE) {
        var lookup = this._lookup;
        lookupTo = lookup.to;
        lookupFrom = lookup.from;
      }
      this.powStub.setExtent2(kind, lookupTo[LOOKUP_IDX_EXTENT_START] = start, lookupTo[LOOKUP_IDX_EXTENT_END] = end);
      var base = this.base;
      this.intervalStub.setExtent2(kind, lookupFrom[LOOKUP_IDX_EXTENT_START] = logScaleLogTick(start, base), lookupFrom[LOOKUP_IDX_EXTENT_END] = logScaleLogTick(end, base));
    },
    getFilter: function () {
      return {
        g: 0
      };
    },
    sanitize: function (value, dataExtent) {
      // Conservative - if dataExtent is invalid, do not sanitize.
      if (isValidBoundsForExtent(dataExtent[0], dataExtent[1]) && isNullableNumberFinite(value) && value <= 0) {
        // `DataStore` has ensured that `dataExtent` is valid for LogScale.
        value = dataExtent[0];
      }
      return value;
    },
    getDefaultStartValue: function () {
      return 1;
    },
    getExtent: function () {
      return this.powStub.getExtent();
    },
    getExtentUnsafe: function (kind, depth) {
      return depth === null ? this.powStub.getExtentUnsafe(kind, null) : this.intervalStub.getExtentUnsafe(kind, depth);
    }
  };
  return LogScale;
}(Scale);
Scale.registerClass(LogScale);
var tmpTransformOutOpt1 = {};
var tmpTransformOutOpt2 = {};
var tmpNotUsedArr = [];
export default LogScale;