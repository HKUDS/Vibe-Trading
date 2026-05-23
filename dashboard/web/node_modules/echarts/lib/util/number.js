
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
/*
* A third-party license is embedded for some of the code in this file:
* The method "quantile" was copied from "d3.js".
* (See more details in the comment of the method below.)
* The use of the source code of this file is also subject to the terms
* and consitions of the license of "d3.js" (BSD-3Clause, see
* </licenses/LICENSE-d3>).
*/
import * as zrUtil from 'zrender/lib/core/util.js';
var RADIAN_EPSILON = 1e-4;
// A `RangeError` may be thrown if `n` is out of this range when calling `toFixed(n)`.
// Although Chrome and ES2017+ have enlarged this number to 100, but we sill follow
// the ES3~ES6 spec (0 <= n <= 20) for backward and cross-platform compatibility.
var TO_FIXED_SUPPORTED_PRECISION_MAX = 20;
// For rounding error like `2.9999999999999996`, with respect to IEEE754 64bit float.
// NOTICE: It only works when the expected result is a rational number with low
// precision. See method `round` for details.
export var DEFAULT_PRECISION_FOR_ROUNDING_ERROR = 14;
function _trim(str) {
  return str.replace(/^\s+|\s+$/g, '');
}
export var mathMin = Math.min;
export var mathMax = Math.max;
export var mathAbs = Math.abs;
export var mathRound = Math.round;
export var mathFloor = Math.floor;
export var mathCeil = Math.ceil;
export var mathPow = Math.pow;
export var mathLog = Math.log;
export var mathLN10 = Math.LN10;
export var mathPI = Math.PI;
export var mathRandom = Math.random;
/**
 * Linear mapping a value from domain to range
 * @param  val
 * @param  domain Domain extent domain[0] can be bigger than domain[1]
 * @param  range  Range extent range[0] can be bigger than range[1]
 * @param  clamp Default to be false
 */
export function linearMap(val, domain, range, clamp) {
  var d0 = domain[0];
  var d1 = domain[1];
  var r0 = range[0];
  var r1 = range[1];
  var subDomain = d1 - d0;
  var subRange = r1 - r0;
  if (subDomain === 0) {
    return subRange === 0 ? r0 : (r0 + r1) / 2;
  }
  // Avoid accuracy problem in edge, such as
  // 146.39 - 62.83 === 83.55999999999999.
  // See echarts/test/ut/spec/util/number.js#linearMap#accuracyError
  // It is a little verbose for efficiency considering this method
  // is a hotspot.
  if (clamp) {
    if (subDomain > 0) {
      if (val <= d0) {
        return r0;
      } else if (val >= d1) {
        return r1;
      }
    } else {
      if (val >= d0) {
        return r0;
      } else if (val <= d1) {
        return r1;
      }
    }
  } else {
    if (val === d0) {
      return r0;
    }
    if (val === d1) {
      return r1;
    }
  }
  return (val - d0) / subDomain * subRange + r0;
}
/**
 * Preserve the name `parsePercent` for backward compatibility,
 * and it's effectively published as `echarts.number.parsePercent`.
 */
export var parsePercent = parsePositionOption;
/**
 * @see {parsePositionSizeOption} and also accept a string preset.
 * @see {PositionSizeOption}
 */
export function parsePositionOption(option, percentBase, percentOffset) {
  switch (option) {
    case 'center':
    case 'middle':
      option = '50%';
      break;
    case 'left':
    case 'top':
      option = '0%';
      break;
    case 'right':
    case 'bottom':
      option = '100%';
      break;
  }
  return parsePositionSizeOption(option, percentBase, percentOffset);
}
/**
 * Accept number, or numeric string (`'123'`), or percentage ('100%'), as x/y/width/height pixel number.
 * If null/undefined or invalid, return NaN.
 * (But allow JS type coercion (`+option`) due to backward compatibility)
 * @see {PositionSizeOption}
 */
export function parsePositionSizeOption(option, percentBase,
// Typical usage of `percentOffset`: percent value is based on an specific rect rather than canvas viewport:
//  `parsePercent(percentOrAbsoluteLeft, rect.width, rect.x)`
percentOffset) {
  if (zrUtil.isString(option)) {
    if (isOptionStringPercent(option)) {
      return parseFloat(option) / 100 * percentBase + (percentOffset || 0);
    }
    return parseFloat(option);
  }
  // Allow flexible input due to backward compatibility.
  return option == null ? NaN : +option;
}
/**
 * Perserve the same rule with `parsePositionSizeOption`.
 */
export function isPositionSizeOptionPercent(option) {
  return zrUtil.isString(option) && isOptionStringPercent(option);
}
function isOptionStringPercent(option) {
  return !!_trim(option).match(/%$/);
}
export function round(x, precision, returnStr) {
  if (process.env.NODE_ENV !== 'production') {
    // NOTICE: We should not provided a default precision, since there is no universally adaptable
    // precision. The caller need to input a precision according to the scenarios.
    zrUtil.assert(precision != null);
  }
  if (isNaN(precision)) {
    // precision utils (such as getAcceptableTickPrecision) may return NaN.
    return returnStr ? '' + x : +x;
  }
  // Avoid range error
  precision = mathMin(mathMax(0, precision), TO_FIXED_SUPPORTED_PRECISION_MAX);
  // PENDING: 1.005.toFixed(2) is '1.00' rather than '1.01'
  x = (+x).toFixed(precision);
  return returnStr ? x : +x;
}
export function roundLegacy(x, precision, returnStr) {
  if (precision == null) {
    precision = 10;
  }
  return round(x, precision, returnStr);
}
/**
 * Inplacd asc sort arr.
 * The input arr will be modified.
 */
export function asc(arr) {
  arr.sort(function (a, b) {
    return a - b;
  });
  return arr;
}
/**
 * Get precision.
 * e.g. `getPrecisionSafe(100.123)` return `3`.
 * e.g. `getPrecisionSafe(100)` return `0`.
 */
export function getPrecision(val) {
  val = +val;
  if (isNaN(val)) {
    return 0;
  }
  // It is much faster than methods converting number to string as follows
  //      let tmp = val.toString();
  //      return tmp.length - 1 - tmp.indexOf('.');
  // especially when precision is low
  // Notice:
  // (1) If the loop count is over about 20, it is slower than `getPrecisionSafe`.
  //     (see https://jsbench.me/2vkpcekkvw/1)
  // (2) If the val is less than for example 1e-15, the result may be incorrect.
  //     (see test/ut/spec/util/number.test.ts `getPrecision_equal_random`)
  if (val > 1e-14) {
    var e = 1;
    for (var i = 0; i < 15; i++, e *= 10) {
      if (mathRound(val * e) / e === val) {
        return i;
      }
    }
  }
  return getPrecisionSafe(val);
}
/**
 * Get precision with slow but safe method
 * e.g. `getPrecisionSafe(100.123)` return `3`.
 * e.g. `getPrecisionSafe(100)` return `0`.
 */
export function getPrecisionSafe(val) {
  // toLowerCase for: '3.4E-12'
  var str = val.toString().toLowerCase();
  // Consider scientific notation: '3.4e-12' '3.4e+12'
  var eIndex = str.indexOf('e');
  var exp = eIndex > 0 ? +str.slice(eIndex + 1) : 0;
  var significandPartLen = eIndex > 0 ? eIndex : str.length;
  var dotIndex = str.indexOf('.');
  var decimalPartLen = dotIndex < 0 ? 0 : significandPartLen - 1 - dotIndex;
  return mathMax(0, decimalPartLen - exp);
}
/**
 * @deprecated Use `getAcceptableTickPrecision` instead. See bad case in `test/ut/spec/util/number.test.ts`
 * NOTE: originally introduced in commit `ff93e3e7f9ff24902e10d4469fd3187393b05feb`
 *
 * Minimal discernible data precision according to a single pixel.
 */
export function getPixelPrecision(dataExtent, pixelExtent) {
  var dataQuantity = mathFloor(mathLog(dataExtent[1] - dataExtent[0]) / mathLN10);
  var sizeQuantity = mathRound(mathLog(mathAbs(pixelExtent[1] - pixelExtent[0])) / mathLN10);
  // toFixed() digits argument must be between 0 and 20.
  var precision = mathMin(mathMax(-dataQuantity + sizeQuantity, 0), TO_FIXED_SUPPORTED_PRECISION_MAX);
  return !isFinite(precision) ? TO_FIXED_SUPPORTED_PRECISION_MAX : precision;
}
/**
 * This method chooses a reasonable "data" precision that can be used in `round` method.
 * A reasonable precision is suitable for display; it may cause cumulative error but acceptable.
 *
 * "data" is linearly mapped to pixel according to the ratio determined by `dataSpan` and `pxSpan`.
 * The diff from the original "data" to the rounded "data" (with the result precision) should be
 * equal or less than `pxDiffAcceptable`, which is typically `1` pixel.
 * And the result precision should be as small as possible for a concise display.
 *
 * [NOTICE]: using arbitrary parameters is NOT preferable - a discernible misalign (e.g., over 1px)
 *  may occur, especially when `splitLine` is displayed.
 *
 * PENDING: Only the linear case is addressed for now; other mapping methods (like logarithm) will
 *  not be covered until necessary.
 */
export function getAcceptableTickPrecision(dataExtent,
// Typically, `Math.abs(pixelExtent[1] - pixelExtent[0])`.
pxSpan,
// By default, `1`.
pxDiffAcceptable
// Return a precision >= 0
// This precision can be used in method `round`.
// Return `NaN` for edge case or illegal inputs. Callers need to handle that.
) {
  var dataSpan = mathAbs(dataExtent[1] - dataExtent[0]);
  if (!isFinite(dataSpan) || dataSpan === 0) {
    return NaN;
  }
  // Formula for choosing an acceptable precision:
  //  Let `pxDiff = abs(dataSpan - round(dataSpan, precision))`.
  //  We require `pxDiff <= dataSpan * pxDiffAcceptable / pxSpan`.
  //  Consider the nature of "round", the max `pxDiff` is: `pow(10, -precision) / 2`,
  //  Hence: `pow(10, -precision) / 2 <= dataSpan * pxDiffAcceptable / pxSpan`
  //  Hence: `precision >= -log10(2 * dataSpan * pxDiffAcceptable / pxSpan)`
  var dataExp2 = mathLog(2 * mathAbs(pxDiffAcceptable || 1) * mathAbs(dataSpan)) / mathLN10;
  var pxExp = mathLog(mathAbs(pxSpan)) / mathLN10;
  // PENDING: Rounding error generally does not matter; do not fix it before `Math.ceil`
  // until bad case occur.
  var precision = mathMax(0, mathCeil(-dataExp2 + pxExp));
  if (!isFinite(precision)) {
    // If dataSpan is near `0`, the result should not be too big or even `Infinity`.
    precision = NaN;
  }
  return precision;
}
/**
 * Get a data of given precision, assuring the sum of percentages
 * in valueList is 1.
 * The largest remainder method is used.
 * https://en.wikipedia.org/wiki/Largest_remainder_method
 *
 * @param valueList a list of all data
 * @param idx index of the data to be processed in valueList
 * @param precision integer number showing digits of precision
 * @return percent ranging from 0 to 100
 */
export function getPercentWithPrecision(valueList, idx, precision) {
  if (!valueList[idx]) {
    return 0;
  }
  var seats = getPercentSeats(valueList, precision);
  return seats[idx] || 0;
}
/**
 * Get a data of given precision, assuring the sum of percentages
 * in valueList is 1.
 * The largest remainder method is used.
 * https://en.wikipedia.org/wiki/Largest_remainder_method
 *
 * @param valueList a list of all data
 * @param precision integer number showing digits of precision
 * @return {Array<number>}
 */
export function getPercentSeats(valueList, precision) {
  var sum = zrUtil.reduce(valueList, function (acc, val) {
    return acc + (isNaN(val) ? 0 : val);
  }, 0);
  if (sum === 0) {
    return [];
  }
  var digits = mathPow(10, precision);
  var votesPerQuota = zrUtil.map(valueList, function (val) {
    return (isNaN(val) ? 0 : val) / sum * digits * 100;
  });
  var targetSeats = digits * 100;
  var seats = zrUtil.map(votesPerQuota, function (votes) {
    // Assign automatic seats.
    return mathFloor(votes);
  });
  var currentSum = zrUtil.reduce(seats, function (acc, val) {
    return acc + val;
  }, 0);
  var remainder = zrUtil.map(votesPerQuota, function (votes, idx) {
    return votes - seats[idx];
  });
  // Has remainding votes.
  while (currentSum < targetSeats) {
    // Find next largest remainder.
    var max = Number.NEGATIVE_INFINITY;
    var maxId = null;
    for (var i = 0, len = remainder.length; i < len; ++i) {
      if (remainder[i] > max) {
        max = remainder[i];
        maxId = i;
      }
    }
    // Add a vote to max remainder.
    ++seats[maxId];
    remainder[maxId] = 0;
    ++currentSum;
  }
  return zrUtil.map(seats, function (seat) {
    return seat / digits;
  });
}
/**
 * Solve the floating point adding problem like 0.1 + 0.2 === 0.30000000000000004
 * See <http://0.30000000000000004.com/>
 */
export function addSafe(val0, val1) {
  var maxPrecision = mathMax(getPrecision(val0), getPrecision(val1));
  // const multiplier = Math.pow(10, maxPrecision);
  // return (mathRound(val0 * multiplier) + mathRound(val1 * multiplier)) / multiplier;
  var sum = val0 + val1;
  // // PENDING: support more?
  return maxPrecision > TO_FIXED_SUPPORTED_PRECISION_MAX ? sum : round(sum, maxPrecision);
}
// Number.MAX_SAFE_INTEGER, ie do not support.
export var MAX_SAFE_INTEGER = mathPow(2, 53) - 1;
/**
 * To 0 - 2 * PI, considering negative radian.
 */
export function remRadian(radian) {
  var pi2 = mathPI * 2;
  return (radian % pi2 + pi2) % pi2;
}
/**
 * @param {type} radian
 * @return {boolean}
 */
export function isRadianAroundZero(val) {
  return val > -RADIAN_EPSILON && val < RADIAN_EPSILON;
}
// eslint-disable-next-line
var TIME_REG = /^(?:(\d{4})(?:[-\/](\d{1,2})(?:[-\/](\d{1,2})(?:[T ](\d{1,2})(?::(\d{1,2})(?::(\d{1,2})(?:[.,](\d+))?)?)?(Z|[\+\-]\d\d:?\d\d)?)?)?)?)?$/; // jshint ignore:line
/**
 * @param value valid type: number | string | Date, otherwise return `new Date(NaN)`
 *   These values can be accepted:
 *   + An instance of Date, represent a time in its own time zone.
 *   + Or string in a subset of ISO 8601, only including:
 *     + only year, month, date: '2012-03', '2012-03-01', '2012-03-01 05', '2012-03-01 05:06',
 *     + separated with T or space: '2012-03-01T12:22:33.123', '2012-03-01 12:22:33.123',
 *     + time zone: '2012-03-01T12:22:33Z', '2012-03-01T12:22:33+8000', '2012-03-01T12:22:33-05:00',
 *     all of which will be treated as local time if time zone is not specified
 *     (see <https://momentjs.com/>).
 *   + Or other string format, including (all of which will be treated as local time):
 *     '2012', '2012-3-1', '2012/3/1', '2012/03/01',
 *     '2009/6/12 2:00', '2009/6/12 2:05:08', '2009/6/12 2:05:08.123'
 *   + a timestamp, which represent a time in UTC.
 * @return date Never be null/undefined. If invalid, return `new Date(NaN)`.
 */
export function parseDate(value) {
  if (value instanceof Date) {
    return value;
  } else if (zrUtil.isString(value)) {
    // Different browsers parse date in different way, so we parse it manually.
    // Some other issues:
    // new Date('1970-01-01') is UTC,
    // new Date('1970/01/01') and new Date('1970-1-01') is local.
    // See issue #3623
    var match = TIME_REG.exec(value);
    if (!match) {
      // return Invalid Date.
      return new Date(NaN);
    }
    // Use local time when no timezone offset is specified.
    if (!match[8]) {
      // match[n] can only be string or undefined.
      // But take care of '12' + 1 => '121'.
      return new Date(+match[1], +(match[2] || 1) - 1, +match[3] || 1, +match[4] || 0, +(match[5] || 0), +match[6] || 0, match[7] ? +match[7].substring(0, 3) : 0);
    }
    // Timezoneoffset of Javascript Date has considered DST (Daylight Saving Time,
    // https://tc39.github.io/ecma262/#sec-daylight-saving-time-adjustment).
    // For example, system timezone is set as "Time Zone: America/Toronto",
    // then these code will get different result:
    // `new Date(1478411999999).getTimezoneOffset();  // get 240`
    // `new Date(1478412000000).getTimezoneOffset();  // get 300`
    // So we should not use `new Date`, but use `Date.UTC`.
    else {
      var hour = +match[4] || 0;
      if (match[8].toUpperCase() !== 'Z') {
        hour -= +match[8].slice(0, 3);
      }
      return new Date(Date.UTC(+match[1], +(match[2] || 1) - 1, +match[3] || 1, hour, +(match[5] || 0), +match[6] || 0, match[7] ? +match[7].substring(0, 3) : 0));
    }
  } else if (value == null) {
    return new Date(NaN);
  }
  return new Date(mathRound(value));
}
/**
 * Quantity of a number. e.g. 0.1, 1, 10, 100
 *
 * @param val
 * @return
 */
export function quantity(val) {
  return mathPow(10, quantityExponent(val));
}
/**
 * Exponent of the quantity of a number
 * e.g., 9876 equals to 9.876*10^3, so quantityExponent(9876) is 3
 * e.g., 0.09876 equals to 9.876*10^-2, so quantityExponent(0.09876) is -2
 *
 * @param val non-negative value
 * @return
 */
export function quantityExponent(val) {
  if (val === 0) {
    // PENDING: like IEEE754 use exponent `0` in this case.
    // but methematically, exponent of zero is `-Infinity`.
    return 0;
  }
  var exp = mathFloor(mathLog(val) / mathLN10);
  /**
   * exp is expected to be the rounded-down result of the base-10 log of val.
   * But due to the precision loss with Math.log(val), we need to restore it
   * using 10^exp to make sure we can get val back from exp. #11249
   */
  if (val / mathPow(10, exp) >= 10) {
    exp++;
  }
  return exp;
}
export var NICE_MODE_ROUND = 1;
export var NICE_MODE_MIN = 2;
/**
 * find a “nice” number approximately equal to x. Round the number if 'round',
 * take ceiling if 'round'. The primary observation is that the “nicest”
 * numbers in decimal are 1, 2, and 5, and all power-of-ten multiples of these numbers.
 *
 * See "Nice Numbers for Graph Labels" of Graphic Gems.
 *
 * @param  val Non-negative value.
 * @return Niced number
 */
export function nice(val,
// All non-`NICE_MODE_MIN`-truthy values means `NICE_MODE_ROUND`, for backward compatibility.
mode) {
  // Consider the scientific notation of `val`:
  //  - `exponent` is its exponent.
  //  - `f` is its coefficient. `1 <= f < 10`.
  //  e.g., if `val` is `0.0054321`, `exponent` is `-3`, `f` is `5.4321`,
  //      The result is `0.005` on NICE_MODE_ROUND.
  //  e.g., if `val` is `987.12345`, `exponent` is `2`, `f` is `9.8712345`,
  //      The result is `1000` on NICE_MODE_ROUND.
  //  e.g., if `val` is `0`,
  //      The result is `1`.
  var exponent = quantityExponent(val);
  // No rounding error in Math.pow(10, integer).
  var exp10 = mathPow(10, exponent);
  var f = val / exp10;
  var nf;
  if (mode === NICE_MODE_MIN) {
    nf = 1;
  } else if (mode) {
    if (f < 1.5) {
      nf = 1;
    } else if (f < 2.5) {
      nf = 2;
    } else if (f < 4) {
      nf = 3;
    } else if (f < 7) {
      nf = 5;
    } else {
      nf = 10;
    }
  } else {
    if (f < 1) {
      nf = 1;
    } else if (f < 2) {
      nf = 2;
    } else if (f < 3) {
      nf = 3;
    } else if (f < 5) {
      nf = 5;
    } else {
      nf = 10;
    }
  }
  val = nf * exp10;
  // Fix IEEE 754 float rounding error
  return round(val, -exponent);
}
/**
 * This code was copied from "d3.js"
 * <https://github.com/d3/d3/blob/9cc9a875e636a1dcf36cc1e07bdf77e1ad6e2c74/src/arrays/quantile.js>.
 * See the license statement at the head of this file.
 * @param ascArr
 */
export function quantile(ascArr, p) {
  var H = (ascArr.length - 1) * p + 1;
  var h = mathFloor(H);
  var v = +ascArr[h - 1];
  var e = H - h;
  return e ? v + e * (ascArr[h] - v) : v;
}
/**
 * Order intervals asc, and split them when overlap.
 * expect(numberUtil.reformIntervals([
 *     {interval: [18, 62], close: [1, 1]},
 *     {interval: [-Infinity, -70], close: [0, 0]},
 *     {interval: [-70, -26], close: [1, 1]},
 *     {interval: [-26, 18], close: [1, 1]},
 *     {interval: [62, 150], close: [1, 1]},
 *     {interval: [106, 150], close: [1, 1]},
 *     {interval: [150, Infinity], close: [0, 0]}
 * ])).toEqual([
 *     {interval: [-Infinity, -70], close: [0, 0]},
 *     {interval: [-70, -26], close: [1, 1]},
 *     {interval: [-26, 18], close: [0, 1]},
 *     {interval: [18, 62], close: [0, 1]},
 *     {interval: [62, 150], close: [0, 1]},
 *     {interval: [150, Infinity], close: [0, 0]}
 * ]);
 * @param list, where `close` mean open or close
 *        of the interval, and Infinity can be used.
 * @return The origin list, which has been reformed.
 */
export function reformIntervals(list) {
  list.sort(function (a, b) {
    return littleThan(a, b, 0) ? -1 : 1;
  });
  var curr = -Infinity;
  var currClose = 1;
  for (var i = 0; i < list.length;) {
    var interval = list[i].interval;
    var close_1 = list[i].close;
    for (var lg = 0; lg < 2; lg++) {
      if (interval[lg] <= curr) {
        interval[lg] = curr;
        close_1[lg] = !lg ? 1 - currClose : 1;
      }
      curr = interval[lg];
      currClose = close_1[lg];
    }
    if (interval[0] === interval[1] && close_1[0] * close_1[1] !== 1) {
      list.splice(i, 1);
    } else {
      i++;
    }
  }
  return list;
  function littleThan(a, b, lg) {
    return a.interval[lg] < b.interval[lg] || a.interval[lg] === b.interval[lg] && (a.close[lg] - b.close[lg] === (!lg ? 1 : -1) || !lg && littleThan(a, b, 1));
  }
}
/**
 * [Numeric is defined as]:
 *     `parseFloat(val) == val`
 * For example:
 * numeric:
 *     typeof number except NaN, '-123', '123', '2e3', '-2e3', '011', 'Infinity', Infinity,
 *     and they rounded by white-spaces or line-terminal like ' -123 \n ' (see es spec)
 * not-numeric:
 *     null, undefined, [], {}, true, false, 'NaN', NaN, '123ab',
 *     empty string, string with only white-spaces or line-terminal (see es spec),
 *     0x12, '0x12', '-0x12', 012, '012', '-012',
 *     non-string, ...
 *
 * @test See full test cases in `test/ut/spec/util/number.js`.
 * @return Must be a typeof number. If not numeric, return NaN.
 */
export function numericToNumber(val) {
  var valFloat = parseFloat(val);
  return valFloat == val // eslint-disable-line eqeqeq
  && (valFloat !== 0 || !zrUtil.isString(val) || val.indexOf('x') <= 0) // For case ' 0x0 '.
  ? valFloat : NaN;
}
/**
 * Definition of "numeric": see `numericToNumber`.
 */
export function isNumeric(val) {
  return !isNaN(numericToNumber(val));
}
/**
 * Use random base to prevent users hard code depending on
 * this auto generated marker id.
 * @return An positive integer.
 */
export function getRandomIdBase() {
  return mathRound(mathRandom() * 9);
}
/**
 * Get the greatest common divisor.
 *
 * @param {number} a one number
 * @param {number} b the other number
 */
export function getGreatestCommonDividor(a, b) {
  if (b === 0) {
    return a;
  }
  return getGreatestCommonDividor(b, a % b);
}
/**
 * Get the least common multiple.
 *
 * @param {number} a one number
 * @param {number} b the other number
 */
export function getLeastCommonMultiple(a, b) {
  if (a == null) {
    return b;
  }
  if (b == null) {
    return a;
  }
  return a * b / getGreatestCommonDividor(a, b);
}
/**
 * NOTICE: Assume the input `val` is number or null/undefined, no type check, no support of BitInt.
 * Therefore, it is NOT suitable for processing user input, but sufficient for
 * internal usage in most cases.
 * For platform-agnosticism, `Number.isFinite` is not used.
 */
export function isNullableNumberFinite(val) {
  return val != null && isFinite(val);
}