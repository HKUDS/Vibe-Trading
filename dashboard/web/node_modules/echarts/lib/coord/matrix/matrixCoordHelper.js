
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
import { eqNaN, isArray, isNumber } from 'zrender/lib/core/util.js';
import { WH, XY } from '../../util/graphic.js';
import { mathMax, mathMin } from '../../util/number.js';
export var MatrixCellLayoutInfoType = {
  level: 1,
  leaf: 2,
  nonLeaf: 3
};
/**
 * @public Public to users in `chart.convertFromPixel`.
 */
export var MatrixClampOption = {
  // No clamp, be falsy, equals to null/undefined. It means if the input part is
  // null/undefined/NaN/outOfBoundary, the result part is NaN, rather than clamp to
  // the boundary of the matrix.
  none: 0,
  // Clamp, where null/undefined/NaN/outOfBoundary can be used to cover the entire row/column.
  all: 1,
  body: 2,
  corner: 3
};
/**
 * For the x direction,
 *  - find dimension cell from `xMatrixDim`,
 *      - If `xDimCell` or `yDimCell` is not a leaf, return the non-leaf cell itself.
 *  - otherwise find level from `yMatrixDim`.
 *  - otherwise return `NullUndefined`.
 *
 * For the y direction, it's the opposite.
 */
export function coordDataToAllCellLevelLayout(coordValue, dims, thisDimIdx // 0 | 1
) {
  // Find in body.
  var result = dims[XY[thisDimIdx]].getCell(coordValue);
  // Find in corner or dimension area.
  if (!result && isNumber(coordValue) && coordValue < 0) {
    result = dims[XY[1 - thisDimIdx]].getUnitLayoutInfo(thisDimIdx, Math.round(coordValue));
  }
  return result;
}
export function resetXYLocatorRange(out) {
  var rg = out || [];
  rg[0] = rg[0] || [];
  rg[1] = rg[1] || [];
  rg[0][0] = rg[0][1] = rg[1][0] = rg[1][1] = NaN;
  return rg;
}
/**
 * If illegal or out of boundary, set NaN to `locOut`. See `isXYLocatorRangeInvalidOnDim`.
 * x dimension and y dimension are calculated separately.
 */
export function parseCoordRangeOption(locOut,
// If illegal input or can not find any target, save reason to it.
// Do nothing if `NullUndefined`.
reasonOut, data, dims, clamp) {
  // x and y are supported to be handled separately - if one dimension is invalid
  // (may be users do not need that), the other one should also be calculated.
  parseCoordRangeOptionOnOneDim(locOut[0], reasonOut, clamp, data, dims, 0);
  parseCoordRangeOptionOnOneDim(locOut[1], reasonOut, clamp, data, dims, 1);
}
function parseCoordRangeOptionOnOneDim(locDimOut, reasonOut, clamp, data, dims, dimIdx) {
  locDimOut[0] = Infinity;
  locDimOut[1] = -Infinity;
  var dataOnDim = data[dimIdx];
  var coordValArr = isArray(dataOnDim) ? dataOnDim : [dataOnDim];
  var len = coordValArr.length;
  var hasClamp = !!clamp;
  if (len >= 1) {
    parseCoordRangeOptionOnOneDimOnePart(locDimOut, reasonOut, coordValArr, hasClamp, dims, dimIdx, 0);
    if (len > 1) {
      // Users may intuitively input the coords like `[[x1, x2, x3], ...]`;
      // consider the range as `[x1, x3]` in this case.
      parseCoordRangeOptionOnOneDimOnePart(locDimOut, reasonOut, coordValArr, hasClamp, dims, dimIdx, len - 1);
    }
  } else {
    if (process.env.NODE_ENV !== 'production') {
      if (reasonOut) {
        reasonOut.push('Should be like [["x1", "x2"], ["y1", "y2"]], or ["x1", "y1"], rather than empty.');
      }
    }
    locDimOut[0] = locDimOut[1] = NaN;
  }
  if (hasClamp) {
    // null/undefined/NaN or illegal data represents the entire row/column;
    // Cover the entire locator regardless of body or corner, and confine it later.
    var locLowerBound = -dims[XY[1 - dimIdx]].getLocatorCount(dimIdx);
    var locUpperBound = dims[XY[dimIdx]].getLocatorCount(dimIdx) - 1;
    if (clamp === MatrixClampOption.body) {
      locLowerBound = mathMax(0, locLowerBound);
    } else if (clamp === MatrixClampOption.corner) {
      locUpperBound = mathMin(-1, locUpperBound);
    }
    if (locUpperBound < locLowerBound) {
      // Also considered that both x and y has no cell.
      locLowerBound = locUpperBound = NaN;
    }
    if (eqNaN(locDimOut[0])) {
      locDimOut[0] = locLowerBound;
    }
    if (eqNaN(locDimOut[1])) {
      locDimOut[1] = locUpperBound;
    }
    locDimOut[0] = mathMax(mathMin(locDimOut[0], locUpperBound), locLowerBound);
    locDimOut[1] = mathMax(mathMin(locDimOut[1], locUpperBound), locLowerBound);
  }
}
// The return val must be finite or NaN.
function parseCoordRangeOptionOnOneDimOnePart(locDimOut, reasonOut, coordValArr, hasClamp, dims, dimIdx, partIdx) {
  var layout = coordDataToAllCellLevelLayout(coordValArr[partIdx], dims, dimIdx);
  if (!layout) {
    if (process.env.NODE_ENV !== 'production') {
      if (!hasClamp && reasonOut) {
        reasonOut.push("Can not find cell by coord[" + dimIdx + "][" + partIdx + "].");
      }
    }
    locDimOut[0] = locDimOut[1] = NaN;
    return;
  }
  var locatorA = layout.id[XY[dimIdx]];
  var locatorB = locatorA;
  var dimCell = cellLayoutInfoToDimCell(layout);
  if (dimCell) {
    // Handle non-leaf
    locatorB += dimCell.span[XY[dimIdx]] - 1;
  }
  locDimOut[0] = mathMin(locDimOut[0], locatorA, locatorB);
  locDimOut[1] = mathMax(locDimOut[1], locatorA, locatorB);
}
/**
 * @param locatorRange Must be the return of `parseCoordRangeOption`,
 *  where if not NaN, it must be a valid locator.
 */
export function isXYLocatorRangeInvalidOnDim(locatorRange, dimIdx) {
  return eqNaN(locatorRange[dimIdx][0]) || eqNaN(locatorRange[dimIdx][1]);
}
// `locatorRange` will be expanded (modified) if an intersection is encountered.
export function resolveXYLocatorRangeByCellMerge(inOutLocatorRange,
// Item indices coorespond to mergeDefList (len: mergeDefListTravelLen).
// Indicating whether each item has be merged into the `locatorRange`
outMergedMarkList, mergeDefList, mergeDefListTravelLen) {
  outMergedMarkList = outMergedMarkList || _tmpOutMergedMarkList;
  for (var idx = 0; idx < mergeDefListTravelLen; idx++) {
    outMergedMarkList[idx] = false;
  }
  // In most case, cell merging definition list length is smaller than the range extent,
  // therefore, to detection intersection, travelling cell merging definition list is probably
  // performant than traveling the four edges of the rect formed by the locator range.
  while (true) {
    var expanded = false;
    for (var idx = 0; idx < mergeDefListTravelLen; idx++) {
      var mergeDef = mergeDefList[idx];
      if (!outMergedMarkList[idx] && mergeDef.cellMergeOwner && expandXYLocatorRangeIfIntersect(inOutLocatorRange, mergeDef.locatorRange)) {
        outMergedMarkList[idx] = true;
        expanded = true;
      }
    }
    if (!expanded) {
      break;
    }
  }
}
var _tmpOutMergedMarkList = [];
// Return whether intersect.
// `thisLocRange` will be expanded (modified) if an intersection is encountered.
function expandXYLocatorRangeIfIntersect(thisLocRange, otherLocRange) {
  if (!locatorRangeIntersectOneDim(thisLocRange[0], otherLocRange[0]) || !locatorRangeIntersectOneDim(thisLocRange[1], otherLocRange[1])) {
    return false;
  }
  thisLocRange[0][0] = mathMin(thisLocRange[0][0], otherLocRange[0][0]);
  thisLocRange[0][1] = mathMax(thisLocRange[0][1], otherLocRange[0][1]);
  thisLocRange[1][0] = mathMin(thisLocRange[1][0], otherLocRange[1][0]);
  thisLocRange[1][1] = mathMax(thisLocRange[1][1], otherLocRange[1][1]);
  return true;
}
// Notice: If containing NaN, not intersect.
function locatorRangeIntersectOneDim(locRange1OneDim, locRange2OneDim) {
  return locRange1OneDim[1] >= locRange2OneDim[0] && locRange1OneDim[0] <= locRange2OneDim[1];
}
export function fillIdSpanFromLocatorRange(owner, locatorRange) {
  owner.id.set(locatorRange[0][0], locatorRange[1][0]);
  owner.span.set(locatorRange[0][1] - owner.id.x + 1, locatorRange[1][1] - owner.id.y + 1);
}
export function cloneXYLocatorRange(target, source) {
  target[0][0] = source[0][0];
  target[0][1] = source[0][1];
  target[1][0] = source[1][0];
  target[1][1] = source[1][1];
}
/**
 * If illegal, the corresponding x/y/width/height is set to `NaN`.
 * `x/width` or `y/height` is supported to be calculated separately,
 * i.e., one side are NaN, the other side are normal.
 * @param oneDimOut only write to `x/width` or `y/height`, depending on `dimIdx`.
 */
export function xyLocatorRangeToRectOneDim(oneDimOut, locRange, dims, dimIdx) {
  var layoutMin = coordDataToAllCellLevelLayout(locRange[dimIdx][0], dims, dimIdx);
  var layoutMax = coordDataToAllCellLevelLayout(locRange[dimIdx][1], dims, dimIdx);
  oneDimOut[XY[dimIdx]] = oneDimOut[WH[dimIdx]] = NaN;
  if (layoutMin && layoutMax) {
    oneDimOut[XY[dimIdx]] = layoutMin.xy;
    oneDimOut[WH[dimIdx]] = layoutMax.xy + layoutMax.wh - layoutMin.xy;
  }
}
// No need currently, since `span` is not allowed to be defined directly by users.
// /**
//  * If either span x or y is valid and > 1, return parsed span, otherwise return `NullUndefined`.
//  */
// export function parseSpanOption(
//     spanOptionHost: MatrixCellSpanOptionHost,
//     dimCellPair: MatrixCellLayoutInfo[]
// ): Point | NullUndefined {
//     const spanX = parseSpanOnDim(spanOptionHost.spanX, dimCellPair[0], 0);
//     const spanY = parseSpanOnDim(spanOptionHost.spanY, dimCellPair[1], 1);
//     if (!eqNaN(spanX) || !eqNaN(spanY)) {
//         return new Point(spanX || 1, spanY || 1);
//     }
//     function parseSpanOnDim(spanOption: unknown, dimCell: MatrixCellLayoutInfo, dimIdx: number): number {
//         if (!isNumber(spanOption)) {
//             return NaN;
//         }
//         // Ensure positive integer (not NaN) to avoid dead loop.
//         const span = mathMax(1, Math.round(spanOption || 1)) || 1;
//         // Clamp, and consider may also be specified as `Infinity` to span the entire col/row.
//         return mathMin(span, mathMax(1, dimCell.dim.getLocatorCount(dimIdx) - dimCell.id[XY[dimIdx]]));
//     }
// }
/**
 * @usage To get/set on dimension, use:
 *  `xyVal[XY[dim]] = val;` // set on this dimension.
 *  `xyVal[XY[1 - dim]] = val;` // set on the perpendicular dimension.
 */
export function setDimXYValue(out, dimIdx,
// 0 | 1
valueOnThisDim, valueOnOtherDim) {
  out[XY[dimIdx]] = valueOnThisDim;
  out[XY[1 - dimIdx]] = valueOnOtherDim;
  return out;
}
/**
 * Return NullUndefined if not dimension cell.
 */
function cellLayoutInfoToDimCell(cellLayoutInfo) {
  return cellLayoutInfo && (cellLayoutInfo.type === MatrixCellLayoutInfoType.leaf || cellLayoutInfo.type === MatrixCellLayoutInfoType.nonLeaf) ? cellLayoutInfo : null;
}
export function createNaNRectLike() {
  return {
    x: NaN,
    y: NaN,
    width: NaN,
    height: NaN
  };
}