
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
import { makeInner } from '../../util/model.js';
import { assert, each, extend, find, map } from 'zrender/lib/core/util.js';
import { getScaleBreakHelper } from '../../scale/break.js';
import { subPixelOptimizeLine } from 'zrender/lib/graphic/helper/subPixelOptimize.js';
import { applyTransform } from 'zrender/lib/core/vector.js';
import * as matrixUtil from 'zrender/lib/core/matrix.js';
import { AXIS_BREAK_COLLAPSE_ACTION_TYPE, AXIS_BREAK_EXPAND_ACTION_TYPE, AXIS_BREAK_TOGGLE_ACTION_TYPE } from './axisAction.js';
import { labelIntersect, labelLayoutApplyTranslation } from '../../label/labelLayoutHelper.js';
import { registerAxisBreakHelperImpl } from './axisBreakHelper.js';
import { warn } from '../../util/log.js';
import { Group, Line, Point, Polygon, Polyline, WH, XY } from '../../util/graphic.js';
/**
 * @caution
 *  Must not export anything except `installAxisBreakHelper`
 */
/**
 * The zigzag shapes for axis breaks are generated according to some random
 * factors. It should persist as much as possible to avoid constantly
 * changing by every user operation.
 */
var viewCache = makeInner();
function ensureVisualInCache(visualList, targetBreak) {
  var visual = find(visualList, function (item) {
    return getScaleBreakHelper().identifyAxisBreak(item.parsedBreak.breakOption, targetBreak.breakOption);
  });
  if (!visual) {
    visualList.push(visual = {
      zigzagRandomList: [],
      parsedBreak: targetBreak,
      shouldRemove: false
    });
  }
  return visual;
}
function resetCacheVisualRemoveFlag(visualList) {
  each(visualList, function (item) {
    return item.shouldRemove = true;
  });
}
function removeUnusedCacheVisual(visualList) {
  for (var i = visualList.length - 1; i >= 0; i--) {
    if (visualList[i].shouldRemove) {
      visualList.splice(i, 1);
    }
  }
}
function rectCoordBuildBreakAxis(axisGroup, axisView, axisModel, coordSysRect, api) {
  var axis = axisModel.axis;
  if (axis.scale.isBlank() || !getScaleBreakHelper()) {
    return;
  }
  var breakPairs = getScaleBreakHelper().retrieveAxisBreakPairs(axis.scale.getTicks({
    breakTicks: 'only_break'
  }), function (tick) {
    return tick["break"];
  }, false);
  if (!breakPairs.length) {
    return;
  }
  var breakAreaModel = axisModel.getModel('breakArea');
  var zigzagAmplitude = breakAreaModel.get('zigzagAmplitude');
  var zigzagMinSpan = breakAreaModel.get('zigzagMinSpan');
  var zigzagMaxSpan = breakAreaModel.get('zigzagMaxSpan');
  // Use arbitrary value to avoid dead loop if user gives inappropriate settings.
  zigzagMinSpan = Math.max(2, zigzagMinSpan || 0);
  zigzagMaxSpan = Math.max(zigzagMinSpan, zigzagMaxSpan || 0);
  var expandOnClick = breakAreaModel.get('expandOnClick');
  var zigzagZ = breakAreaModel.get('zigzagZ');
  var itemStyleModel = breakAreaModel.getModel('itemStyle');
  var itemStyle = itemStyleModel.getItemStyle();
  var borderColor = itemStyle.stroke;
  var borderWidth = itemStyle.lineWidth;
  var borderType = itemStyle.lineDash;
  var color = itemStyle.fill;
  var group = new Group({
    ignoreModelZ: true
  });
  var isAxisHorizontal = axis.isHorizontal();
  var cachedVisualList = viewCache(axisView).visualList || (viewCache(axisView).visualList = []);
  resetCacheVisualRemoveFlag(cachedVisualList);
  var _loop_1 = function (i) {
    var parsedBreak = breakPairs[i][0]["break"].parsedBreak;
    // Even if brk.gap is 0, we should also draw the breakArea because
    // border is sometimes required to be visible (as a line)
    var coords = [];
    coords[0] = axis.toGlobalCoord(axis.dataToCoord(parsedBreak.vmin, true));
    coords[1] = axis.toGlobalCoord(axis.dataToCoord(parsedBreak.vmax, true));
    if (coords[1] < coords[0]) {
      coords.reverse();
    }
    var cachedVisual = ensureVisualInCache(cachedVisualList, parsedBreak);
    cachedVisual.shouldRemove = false;
    var breakGroup = new Group();
    addZigzagShapes(cachedVisual.zigzagRandomList, breakGroup, coords[0], coords[1], isAxisHorizontal, parsedBreak);
    if (expandOnClick) {
      breakGroup.on('click', function () {
        var payload = {
          type: AXIS_BREAK_EXPAND_ACTION_TYPE,
          breaks: [{
            start: parsedBreak.breakOption.start,
            end: parsedBreak.breakOption.end
          }]
        };
        payload[axis.dim + "AxisIndex"] = axisModel.componentIndex;
        api.dispatchAction(payload);
      });
    }
    breakGroup.silent = !expandOnClick;
    group.add(breakGroup);
  };
  for (var i = 0; i < breakPairs.length; i++) {
    _loop_1(i);
  }
  axisGroup.add(group);
  removeUnusedCacheVisual(cachedVisualList);
  function addZigzagShapes(zigzagRandomList, breakGroup, startCoord, endCoord, isAxisHorizontal, trimmedBreak) {
    var polylineStyle = {
      stroke: borderColor,
      lineWidth: borderWidth,
      lineDash: borderType,
      fill: 'none'
    };
    var dimBrk = isAxisHorizontal ? 0 : 1;
    var dimZigzag = 1 - dimBrk;
    var zigzagCoordMax = coordSysRect[XY[dimZigzag]] + coordSysRect[WH[dimZigzag]];
    // Apply `subPixelOptimizeLine` for alignning with break ticks.
    function subPixelOpt(brkCoord) {
      var pBrk = [];
      var dummyP = [];
      pBrk[dimBrk] = dummyP[dimBrk] = brkCoord;
      pBrk[dimZigzag] = coordSysRect[XY[dimZigzag]];
      dummyP[dimZigzag] = zigzagCoordMax;
      var dummyShape = {
        x1: pBrk[0],
        y1: pBrk[1],
        x2: dummyP[0],
        y2: dummyP[1]
      };
      subPixelOptimizeLine(dummyShape, dummyShape, {
        lineWidth: 1
      });
      pBrk[0] = dummyShape.x1;
      pBrk[1] = dummyShape.y1;
      return pBrk[dimBrk];
    }
    startCoord = subPixelOpt(startCoord);
    endCoord = subPixelOpt(endCoord);
    var pointsA = [];
    var pointsB = [];
    var isSwap = true;
    var current = coordSysRect[XY[dimZigzag]];
    for (var idx = 0;; idx++) {
      // Use `isFirstPoint` `isLastPoint` to ensure the intersections between zigzag
      // and axis are precise, thus it can join its axis tick correctly.
      var isFirstPoint = current === coordSysRect[XY[dimZigzag]];
      var isLastPoint = current >= zigzagCoordMax;
      if (isLastPoint) {
        current = zigzagCoordMax;
      }
      var pA = [];
      var pB = [];
      pA[dimBrk] = startCoord;
      pB[dimBrk] = endCoord;
      if (!isFirstPoint && !isLastPoint) {
        pA[dimBrk] += isSwap ? -zigzagAmplitude : zigzagAmplitude;
        pB[dimBrk] -= !isSwap ? -zigzagAmplitude : zigzagAmplitude;
      }
      pA[dimZigzag] = current;
      pB[dimZigzag] = current;
      pointsA.push(pA);
      pointsB.push(pB);
      var randomVal = void 0;
      if (idx < zigzagRandomList.length) {
        randomVal = zigzagRandomList[idx];
      } else {
        randomVal = Math.random();
        zigzagRandomList.push(randomVal);
      }
      current += randomVal * (zigzagMaxSpan - zigzagMinSpan) + zigzagMinSpan;
      isSwap = !isSwap;
      if (isLastPoint) {
        break;
      }
    }
    var anidSuffix = getScaleBreakHelper().serializeAxisBreakIdentifier(trimmedBreak.breakOption);
    // Create two polylines and add them to the breakGroup
    breakGroup.add(new Polyline({
      anid: "break_a_" + anidSuffix,
      shape: {
        points: pointsA
      },
      style: polylineStyle,
      z: zigzagZ
    }));
    /* Add the second polyline and a polygon only if the gap is not zero
     * Otherwise if the polyline is with dashed line or being opaque,
     * it may not be constant with breaks with non-zero gaps. */
    if (trimmedBreak.gapReal !== 0) {
      breakGroup.add(new Polyline({
        anid: "break_b_" + anidSuffix,
        shape: {
          // Not reverse to keep the dash stable when dragging resizing.
          points: pointsB
        },
        style: polylineStyle,
        z: zigzagZ
      }));
      // Creating the polygon that fills the area between the polylines
      // From end to start for polygon.
      var pointsB2 = pointsB.slice();
      pointsB2.reverse();
      var polygonPoints = pointsA.concat(pointsB2);
      breakGroup.add(new Polygon({
        anid: "break_c_" + anidSuffix,
        shape: {
          points: polygonPoints
        },
        style: {
          fill: color,
          opacity: itemStyle.opacity
        },
        z: zigzagZ
      }));
    }
  }
}
function buildAxisBreakLine(axisModel, group, transformGroup, pathBaseProp) {
  var axis = axisModel.axis;
  var transform = transformGroup.transform;
  assert(pathBaseProp.style);
  var extent = axis.getExtent();
  if (axis.inverse) {
    extent = extent.slice();
    extent.reverse();
  }
  var breakPairs = getScaleBreakHelper().retrieveAxisBreakPairs(axis.scale.getTicks({
    breakTicks: 'only_break'
  }), function (tick) {
    return tick["break"];
  }, false);
  var brkLayoutList = map(breakPairs, function (breakPair) {
    var parsedBreak = breakPair[0]["break"].parsedBreak;
    var coordPair = [axis.dataToCoord(parsedBreak.vmin, true), axis.dataToCoord(parsedBreak.vmax, true)];
    coordPair[0] > coordPair[1] && coordPair.reverse();
    return {
      coordPair: coordPair,
      brkId: getScaleBreakHelper().serializeAxisBreakIdentifier(parsedBreak.breakOption)
    };
  });
  brkLayoutList.sort(function (layout1, layout2) {
    return layout1.coordPair[0] - layout2.coordPair[0];
  });
  var ySegMin = extent[0];
  var lastLayout = null;
  for (var idx = 0; idx < brkLayoutList.length; idx++) {
    var layout = brkLayoutList[idx];
    var brkTirmmedMin = Math.max(layout.coordPair[0], extent[0]);
    var brkTirmmedMax = Math.min(layout.coordPair[1], extent[1]);
    if (ySegMin <= brkTirmmedMin) {
      addSeg(ySegMin, brkTirmmedMin, lastLayout, layout);
    }
    ySegMin = brkTirmmedMax;
    lastLayout = layout;
  }
  if (ySegMin <= extent[1]) {
    addSeg(ySegMin, extent[1], lastLayout, null);
  }
  function addSeg(min, max, layout1, layout2) {
    function trans(p1, p2) {
      if (transform) {
        applyTransform(p1, p1, transform);
        applyTransform(p2, p2, transform);
      }
    }
    function subPixelOptimizePP(p1, p2) {
      var shape = {
        x1: p1[0],
        y1: p1[1],
        x2: p2[0],
        y2: p2[1]
      };
      subPixelOptimizeLine(shape, shape, pathBaseProp.style);
      p1[0] = shape.x1;
      p1[1] = shape.y1;
      p2[0] = shape.x2;
      p2[1] = shape.y2;
    }
    var lineP1 = [min, 0];
    var lineP2 = [max, 0];
    // dummy tick is used to align the line segment ends with axis ticks
    // after `subPixelOptimizeLine` being applied.
    var dummyTickEnd1 = [min, 5];
    var dummyTickEnd2 = [max, 5];
    trans(lineP1, dummyTickEnd1);
    subPixelOptimizePP(lineP1, dummyTickEnd1);
    trans(lineP2, dummyTickEnd2);
    subPixelOptimizePP(lineP2, dummyTickEnd2);
    // Apply it keeping the same as the normal axis line.
    subPixelOptimizePP(lineP1, lineP2);
    var seg = new Line(extend({
      shape: {
        x1: lineP1[0],
        y1: lineP1[1],
        x2: lineP2[0],
        y2: lineP2[1]
      }
    }, pathBaseProp));
    group.add(seg);
    // Animation should be precise to be consistent with tick and split line animation.
    seg.anid = "breakLine_" + (layout1 ? layout1.brkId : '\0') + "_\0_" + (layout2 ? layout2.brkId : '\0');
  }
}
/**
 * Resolve the overlap of a pair of labels.
 *
 * [CAUTION] Only label.x/y are allowed to change.
 */
function adjustBreakLabelPair(axisInverse, axisRotation, layoutPair) {
  if (find(layoutPair, function (item) {
    return !item;
  })) {
    return;
  }
  var mtv = new Point();
  if (!labelIntersect(layoutPair[0], layoutPair[1], mtv, {
    // Assert `labelPair` is `[break_min, break_max]`.
    // `axis.inverse: true` means a smaller scale value corresponds to a bigger value in axis.extent.
    // The axisRotation indicates mtv direction of OBB intersecting.
    direction: -(axisInverse ? axisRotation + Math.PI : axisRotation),
    touchThreshold: 0,
    // If need to resovle intersection align axis by moving labels according to MTV,
    // the direction must not be opposite, otherwise cause misleading.
    bidirectional: false
  })) {
    return;
  }
  // Rotate axis back to (1, 0) direction, to be a standard axis.
  var axisStTrans = matrixUtil.create();
  matrixUtil.rotate(axisStTrans, axisStTrans, -axisRotation);
  var labelPairStTrans = map(layoutPair, function (layout) {
    return layout.transform ? matrixUtil.mul(matrixUtil.create(), axisStTrans, layout.transform) : axisStTrans;
  });
  function isParallelToAxis(whIdx) {
    // Assert label[0] and label[1] has the same rotation, so only use [0].
    var localRect = layoutPair[0].localRect;
    var labelVec0 = new Point(localRect[WH[whIdx]] * labelPairStTrans[0][0], localRect[WH[whIdx]] * labelPairStTrans[0][1]);
    return Math.abs(labelVec0.y) < 1e-5;
  }
  // If overlapping, move pair[0] pair[1] apart a little. We need to calculate a ratio k to
  // distribute mtv to pair[0] and pair[1]. This is to place the text gap as close as possible
  // to the center of the break ticks, otherwise it might looks weird or misleading.
  // - When labels' width/height are not parallel to axis (usually by rotation),
  //  we can simply treat the k as `0.5`.
  var k = 0.5;
  // - When labels' width/height are parallel to axis, the width/height need to be considered,
  //  since they may differ significantly. In this case we keep textAlign as 'center' rather
  //  than 'left'/'right', due to considerations of space utilization for wide break.gap.
  //  A sample case: break on xAxis(no inverse) is [200, 300000].
  //  We calculate k based on the formula below:
  //      Rotated axis and labels to the direction of (1, 0).
  //      uval = ( (pair[0].insidePt - mtv*k) + (pair[1].insidePt + mtv*(1-k)) ) / 2 - brkCenter
  //      0 <= k <= 1
  //      |uval| should be as small as possible.
  //  Derived as follows:
  //      qval = (pair[0].insidePt + pair[1].insidePt + mtv) / 2 - brkCenter
  //      k = (qval - uval) / mtv
  //      min(qval, qval-mtv) <= uval <= max(qval, qval-mtv)
  if (isParallelToAxis(0) || isParallelToAxis(1)) {
    var rectSt = map(layoutPair, function (layout, idx) {
      var rect = layout.localRect.clone();
      rect.applyTransform(labelPairStTrans[idx]);
      return rect;
    });
    var brkCenterSt = new Point();
    brkCenterSt.copy(layoutPair[0].label).add(layoutPair[1].label).scale(0.5);
    brkCenterSt.transform(axisStTrans);
    var mtvSt = mtv.clone().transform(axisStTrans);
    var insidePtSum = rectSt[0].x + rectSt[1].x + (mtvSt.x >= 0 ? rectSt[0].width : rectSt[1].width);
    var qval = (insidePtSum + mtvSt.x) / 2 - brkCenterSt.x;
    var uvalMin = Math.min(qval, qval - mtvSt.x);
    var uvalMax = Math.max(qval, qval - mtvSt.x);
    var uval = uvalMax < 0 ? uvalMax : uvalMin > 0 ? uvalMin : 0;
    k = (qval - uval) / mtvSt.x;
  }
  var delta0 = new Point();
  var delta1 = new Point();
  Point.scale(delta0, mtv, -k);
  Point.scale(delta1, mtv, 1 - k);
  labelLayoutApplyTranslation(layoutPair[0], delta0);
  labelLayoutApplyTranslation(layoutPair[1], delta1);
}
function updateModelAxisBreak(model, payload) {
  var result = {
    breaks: []
  };
  each(payload.breaks, function (inputBrk) {
    if (!inputBrk) {
      return;
    }
    var breakOption = find(model.get('breaks', true), function (brkOption) {
      return getScaleBreakHelper().identifyAxisBreak(brkOption, inputBrk);
    });
    if (!breakOption) {
      if (process.env.NODE_ENV !== 'production') {
        warn("Can not find axis break by start: " + inputBrk.start + ", end: " + inputBrk.end);
      }
      return;
    }
    var actionType = payload.type;
    var old = {
      isExpanded: !!breakOption.isExpanded
    };
    breakOption.isExpanded = actionType === AXIS_BREAK_EXPAND_ACTION_TYPE ? true : actionType === AXIS_BREAK_COLLAPSE_ACTION_TYPE ? false : actionType === AXIS_BREAK_TOGGLE_ACTION_TYPE ? !breakOption.isExpanded : breakOption.isExpanded;
    result.breaks.push({
      start: breakOption.start,
      end: breakOption.end,
      isExpanded: !!breakOption.isExpanded,
      old: old
    });
  });
  return result;
}
export function installAxisBreakHelper() {
  registerAxisBreakHelperImpl({
    adjustBreakLabelPair: adjustBreakLabelPair,
    buildAxisBreakLine: buildAxisBreakLine,
    rectCoordBuildBreakAxis: rectCoordBuildBreakAxis,
    updateModelAxisBreak: updateModelAxisBreak
  });
}