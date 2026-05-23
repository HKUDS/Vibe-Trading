
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
import { round, mathRound, mathMin, getPrecision } from '../util/number.js';
import { addCommas } from '../util/format.js';
import Scale from './Scale.js';
import { getIntervalPrecision } from './helper.js';
import { getBreaksUnsafe, getScaleBreakHelper, hasBreaks, simplyParseBreakOption } from './break.js';
import { assert, clone } from 'zrender/lib/core/util.js';
import { getMinorTicks } from './minorTicks.js';
import { getScaleExtentForTickUnsafe, initBreakOrLinearMapper } from './scaleMapper.js';
import { warn } from '../util/log.js';
var IntervalScale = /** @class */function (_super) {
  __extends(IntervalScale, _super);
  function IntervalScale(setting) {
    var _this = _super.call(this) || this;
    _this.type = 'interval';
    _this.parse = IntervalScale.parse;
    setting = setting || {};
    var breakParsed = simplyParseBreakOption(_this, setting);
    var res = initBreakOrLinearMapper(_this, breakParsed, null);
    // @ts-ignore
    _this.brk = res.brk;
    _this._cfg = {
      interval: 0,
      intervalPrecision: 2,
      intervalCount: undefined,
      niceExtent: undefined
    };
    return _this;
  }
  IntervalScale.parse = function (val) {
    // `Scale#parse` (and its overrids) are typically applied at the axis values input
    // in echarts option. e.g., `axis.min/max`, `dataZoom.min/max`, etc.
    // but `series.data` is not included, which uses `dataValueHelper.ts`#`parseDataValue`.
    // `Scale#parse` originally introduced in fb8c813215098b9d2458966229bb95c510883d5e
    // at 2016 for dataZoom start/end settings (See `parseAxisModelMinMax`).
    //
    // Historically `scale/Interval.ts` returns the input value directly. But numeric
    // values (such as a number-like string '123') effectively passed through here and
    // were involved in calculations, which was error-prone and inconsistent with the
    // declared TS return type. Previously such issues are fixed separately in different
    // places case by case (such as #2475).
    //
    // Now, we perform actual parse to ensure its `number` type here. The parsing rule
    // follows the series data parsing rule (`dataValueHelper.ts`#`parseDataValue`)
    // and maintains compatibility as much as possible (thus a more strict parsing
    // `number.ts`#`numericToNumber` is not used here.)
    //
    // FIXME: `ScaleDataValue` also need to be modified to include numeric string type,
    //  since it effectively does.
    return val == null || val === '' ? NaN
    // If string (like '-'), using '+' parse to NaN
    // If object, also parse to NaN
    : Number(val);
  };
  IntervalScale.prototype.getConfig = function () {
    return clone(this._cfg);
  };
  IntervalScale.prototype.setConfig = function (cfg) {
    var extent = getScaleExtentForTickUnsafe(this);
    if (process.env.NODE_ENV !== 'production') {
      assert(cfg.interval != null);
      if (cfg.intervalCount != null) {
        assert(cfg.intervalCount >= -1 && cfg.intervalPrecision != null
        // Do not support intervalCount on axis break currently.
        && !hasBreaks(this));
      }
      if (cfg.niceExtent != null) {
        assert(isFinite(cfg.niceExtent[0]) && isFinite(cfg.niceExtent[1]));
        assert(extent[0] <= cfg.niceExtent[0] && cfg.niceExtent[1] <= extent[1]);
        assert(round(cfg.niceExtent[0] - cfg.niceExtent[1], getPrecision(cfg.interval)) <= cfg.interval);
      }
    }
    // Reset all.
    this._cfg = cfg = clone(cfg);
    if (cfg.niceExtent == null) {
      // Dropped the auto calculated niceExtent and use user-set extent.
      // We assume users want to set both interval and extent to get a better result.
      cfg.niceExtent = extent.slice();
    }
    if (cfg.intervalPrecision == null) {
      cfg.intervalPrecision = getIntervalPrecision(cfg.interval);
    }
  };
  /**
   * In ascending order.
   */
  IntervalScale.prototype.getTicks = function (opt) {
    opt = opt || {};
    var cfg = this._cfg;
    var interval = cfg.interval;
    var extent = getScaleExtentForTickUnsafe(this);
    var niceExtent = cfg.niceExtent;
    var intervalPrecision = cfg.intervalPrecision;
    var scaleBreakHelper = getScaleBreakHelper();
    var brk = this.brk;
    var brkAvailable = scaleBreakHelper && brk;
    var ticks = [];
    // If interval is 0, return [];
    if (!interval) {
      return ticks;
    }
    if (opt.breakTicks === 'only_break' && brkAvailable) {
      scaleBreakHelper.addBreaksToTicks(ticks, brk.breaks, extent);
      return ticks;
    }
    if (process.env.NODE_ENV !== 'production') {
      assert(niceExtent != null);
    }
    // [CAVEAT]: If changing this logic, must sync it to `axisAlignTicks.ts`.
    // A fail-safe is required since `interval` can be user specified, or for the case
    // that using dataZoom toolbox and zoom repeatedly.
    var safeLimit = 3000;
    if (extent[0] < niceExtent[0]) {
      ticks.push({
        value: opt.expandToNicedExtent ? round(niceExtent[0] - interval, intervalPrecision) : extent[0]
      });
    }
    var estimateNiceMultiple = function (tickVal, targetTick) {
      return mathRound((targetTick - tickVal) / interval);
    };
    var intervalCount = cfg.intervalCount;
    for (var tick = niceExtent[0], niceTickIdx = 0;; niceTickIdx++) {
      // Consider case `_extent: [5.2, 5.8], _niceExtent: [6, 5], interval: 1`,
      //  `_intervalCount` makes sense iff `-1`.
      // Consider case `_extent: [5, 5.8], _niceExtent: [5, 5], interval: 1`,
      //  `_intervalCount` makes sense iff `0`.
      if (intervalCount == null) {
        if (tick > niceExtent[1] || !isFinite(tick) || !isFinite(niceExtent[1])) {
          break;
        }
      } else {
        if (niceTickIdx > intervalCount) {
          // nice ticks number should be `intervalCount + 1`
          break;
        }
        // Consider cumulative error, especially caused by rounding, the last nice
        // `tick` may be less than or greater than `niceExtent[1]` slightly.
        tick = mathMin(tick, niceExtent[1]);
        if (niceTickIdx === intervalCount) {
          tick = niceExtent[1];
        }
      }
      ticks.push({
        value: tick
      });
      // Avoid rounding error
      tick = round(tick + interval, intervalPrecision);
      if (brk) {
        var moreMultiple = brk.calcNiceTickMultiple(tick, estimateNiceMultiple);
        if (moreMultiple >= 0) {
          tick = round(tick + moreMultiple * interval, intervalPrecision);
        }
      }
      if (ticks.length > 0 && tick === ticks[ticks.length - 1].value) {
        // Consider out of safe float point, e.g.,
        // -3711126.9907707 + 2e-10 === -3711126.9907707
        break;
      }
      if (ticks.length > safeLimit) {
        if (process.env.NODE_ENV !== 'production') {
          warn('Exceed safe limit in IntervalScale["getTicks"].');
        }
        return [];
      }
    }
    // Consider this case: the last item of ticks is smaller
    // than niceExtent[1] and niceExtent[1] === extent[1].
    var lastNiceTick = ticks.length ? ticks[ticks.length - 1].value : niceExtent[1];
    if (extent[1] > lastNiceTick) {
      ticks.push({
        value: opt.expandToNicedExtent ? round(lastNiceTick + interval, intervalPrecision) : extent[1]
      });
    }
    if (brkAvailable) {
      scaleBreakHelper.pruneTicksByBreak(opt.pruneByBreak, ticks, brk.breaks, function (item) {
        return item.value;
      }, cfg.interval, extent);
    }
    if (brkAvailable && opt.breakTicks !== 'none') {
      scaleBreakHelper.addBreaksToTicks(ticks, brk.breaks, extent);
    }
    return ticks;
  };
  IntervalScale.prototype.getMinorTicks = function (splitNumber) {
    return getMinorTicks(this, splitNumber, getBreaksUnsafe(this), this._cfg.interval);
  };
  IntervalScale.prototype.getLabel = function (tick, opt) {
    if (tick == null) {
      return '';
    }
    var precision = opt && opt.precision;
    if (precision == null) {
      precision = getPrecision(tick.value) || 0;
    } else if (precision === 'auto') {
      // Should be more precise then tick.
      precision = this._cfg.intervalPrecision;
    }
    // (1) If `precision` is set, 12.005 should be display as '12.00500'.
    // (2) Use `round` (toFixed) to avoid scientific notation like '3.5e-7'.
    var dataNum = round(tick.value, precision, true);
    return addCommas(dataNum);
  };
  IntervalScale.type = 'interval';
  return IntervalScale;
}(Scale);
Scale.registerClass(IntervalScale);
export default IntervalScale;