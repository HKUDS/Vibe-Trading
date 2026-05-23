
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
import { OrientedBoundingRect, WH, XY, ensureCopyRect, ensureCopyTransform, expandOrShrinkRect, isBoundingRectAxisAligned } from '../util/graphic.js';
import { LabelMarginType } from './labelStyle.js';
var LABEL_LAYOUT_BASE_PROPS = ['label', 'labelLine', 'layoutOption', 'priority', 'defaultAttr', 'marginForce', 'minMarginForce', 'marginDefault', 'suggestIgnore'];
var LABEL_LAYOUT_DIRTY_BIT_OTHERS = 1;
var LABEL_LAYOUT_DIRTY_BIT_OBB = 2;
var LABEL_LAYOUT_DIRTY_ALL = LABEL_LAYOUT_DIRTY_BIT_OTHERS | LABEL_LAYOUT_DIRTY_BIT_OBB;
export function setLabelLayoutDirty(labelGeometry, dirtyOrClear, dirtyBits) {
  dirtyBits = dirtyBits || LABEL_LAYOUT_DIRTY_ALL;
  dirtyOrClear ? labelGeometry.dirty |= dirtyBits : labelGeometry.dirty &= ~dirtyBits;
}
function isLabelLayoutDirty(labelGeometry, dirtyBits) {
  dirtyBits = dirtyBits || LABEL_LAYOUT_DIRTY_ALL;
  return labelGeometry.dirty == null || !!(labelGeometry.dirty & dirtyBits);
}
/**
 * [CAUTION]
 *  - No auto dirty propagation mechanism yet. If the transform of the raw label or any of its ancestors is
 *    changed, must sync the changes to the props of `LabelGeometry` by:
 *    either explicitly call:
 *      `setLabelLayoutDirty(labelLayout, true); ensureLabelLayoutWithGeometry(labelLayout);`
 *    or call (if only translation is performed):
 *      `labelLayoutApplyTranslation(labelLayout);`
 *  - `label.ignore` is not necessarily falsy, and not considered in computing `LabelGeometry`,
 *    since it might be modified by some overlap resolving handling.
 *  - To duplicate or make a variation:
 *    use `newLabelLayoutWithGeometry`.
 *
 * The result can also be the input of this method.
 * @return `NullUndefined` if and only if `labelLayout` is `NullUndefined`.
 */
export function ensureLabelLayoutWithGeometry(labelLayout) {
  if (!labelLayout) {
    return;
  }
  if (isLabelLayoutDirty(labelLayout)) {
    computeLabelGeometry(labelLayout, labelLayout.label, labelLayout);
  }
  return labelLayout;
}
/**
 * The props in `out` will be filled if existing, or created.
 */
export function computeLabelGeometry(out, label, opt) {
  // [CAUTION] These props may be modified directly for performance consideration,
  //  therefore, do not output the internal data structure of zrender Element.
  var rawTransform = label.getComputedTransform();
  out.transform = ensureCopyTransform(out.transform, rawTransform);
  // NOTE: should call `getBoundingRect` after `getComputedTransform`, or may get an inaccurate bounding rect.
  //  The reason is that `getComputedTransform` calls `__host.updateInnerText()` internally, which updates the label
  //  by `textConfig` mounted on the host.
  // PENDING: add a dirty bit for that in zrender?
  var outLocalRect = out.localRect = ensureCopyRect(out.localRect, label.getBoundingRect());
  var labelStyleExt = label.style;
  var margin = labelStyleExt.margin;
  var marginForce = opt && opt.marginForce;
  var minMarginForce = opt && opt.minMarginForce;
  var marginDefault = opt && opt.marginDefault;
  var marginType = labelStyleExt.__marginType;
  if (marginType == null && marginDefault) {
    margin = marginDefault;
    marginType = LabelMarginType.textMargin;
  }
  // `textMargin` and `minMargin` can not exist both.
  for (var i = 0; i < 4; i++) {
    _tmpLabelMargin[i] = marginType === LabelMarginType.minMargin && minMarginForce && minMarginForce[i] != null ? minMarginForce[i] : marginForce && marginForce[i] != null ? marginForce[i] : margin ? margin[i] : 0;
  }
  if (marginType === LabelMarginType.textMargin) {
    expandOrShrinkRect(outLocalRect, _tmpLabelMargin, false, false);
  }
  var outGlobalRect = out.rect = ensureCopyRect(out.rect, outLocalRect);
  if (rawTransform) {
    outGlobalRect.applyTransform(rawTransform);
  }
  // Notice: label.style.margin is actually `minMargin / 2`, handled by `setTextStyleCommon`.
  if (marginType === LabelMarginType.minMargin) {
    expandOrShrinkRect(outGlobalRect, _tmpLabelMargin, false, false);
  }
  out.axisAligned = isBoundingRectAxisAligned(rawTransform);
  (out.label = out.label || {}).ignore = label.ignore;
  setLabelLayoutDirty(out, false);
  setLabelLayoutDirty(out, true, LABEL_LAYOUT_DIRTY_BIT_OBB);
  // Do not remove `obb` (if existing) for reuse, just reset the dirty bit.
  return out;
}
var _tmpLabelMargin = [0, 0, 0, 0];
/**
 * The props in `out` will be filled if existing, or created.
 */
export function computeLabelGeometry2(out, rawLocalRect, rawTransform) {
  out.transform = ensureCopyTransform(out.transform, rawTransform);
  out.localRect = ensureCopyRect(out.localRect, rawLocalRect);
  out.rect = ensureCopyRect(out.rect, rawLocalRect);
  if (rawTransform) {
    out.rect.applyTransform(rawTransform);
  }
  out.axisAligned = isBoundingRectAxisAligned(rawTransform);
  out.obb = undefined; // Reset to undefined, will be created by `ensureOBB` when using.
  (out.label = out.label || {}).ignore = false;
  return out;
}
/**
 * This is a shortcut of
 *   ```js
 *   labelLayout.label.x = newX;
 *   labelLayout.label.y = newY;
 *   setLabelLayoutDirty(labelLayout, true);
 *   ensureLabelLayoutWithGeometry(labelLayout);
 *   ```
 * and provide better performance in this common case.
 */
export function labelLayoutApplyTranslation(labelLayout, offset) {
  if (!labelLayout) {
    return;
  }
  labelLayout.label.x += offset.x;
  labelLayout.label.y += offset.y;
  labelLayout.label.markRedraw();
  var transform = labelLayout.transform;
  if (transform) {
    transform[4] += offset.x;
    transform[5] += offset.y;
  }
  var globalRect = labelLayout.rect;
  if (globalRect) {
    globalRect.x += offset.x;
    globalRect.y += offset.y;
  }
  var obb = labelLayout.obb;
  if (obb) {
    obb.fromBoundingRect(labelLayout.localRect, transform);
  }
}
/**
 * To duplicate or make a variation of a label layout.
 * Copy the only relevant properties to avoid the conflict or wrongly reuse of the props of `LabelLayoutWithGeometry`.
 */
export function newLabelLayoutWithGeometry(newBaseWithDefaults, source) {
  for (var i = 0; i < LABEL_LAYOUT_BASE_PROPS.length; i++) {
    var prop = LABEL_LAYOUT_BASE_PROPS[i];
    if (newBaseWithDefaults[prop] == null) {
      newBaseWithDefaults[prop] = source[prop];
    }
  }
  return ensureLabelLayoutWithGeometry(newBaseWithDefaults);
}
/**
 * Create obb if no one, can cache it.
 */
function ensureOBB(labelGeometry) {
  var obb = labelGeometry.obb;
  if (!obb || isLabelLayoutDirty(labelGeometry, LABEL_LAYOUT_DIRTY_BIT_OBB)) {
    labelGeometry.obb = obb = obb || new OrientedBoundingRect();
    obb.fromBoundingRect(labelGeometry.localRect, labelGeometry.transform);
    setLabelLayoutDirty(labelGeometry, false, LABEL_LAYOUT_DIRTY_BIT_OBB);
  }
  return obb;
}
/**
 * Adjust labels on x/y direction to avoid overlap.
 *
 * PENDING: the current implementation is based on the global bounding rect rather than the local rect,
 *  which may be not preferable in some edge cases when the label has rotation, but works for most cases,
 *  since rotation is unnecessary when there is sufficient space, while squeezing is applied regardless
 *  of overlapping when there is no enough space.
 *
 * NOTICE:
 *  - The input `list` and its content will be modified (sort, label.x/y, rect).
 *  - The caller should sync the modifications to the other parts by
 *    `setLabelLayoutDirty` and `ensureLabelLayoutWithGeometry` if needed.
 *
 * @return adjusted
 */
export function shiftLayoutOnXY(list, xyDimIdx,
// 0 for x, 1 for y
minBound,
// for x, leftBound; for y, topBound
maxBound,
// for x, rightBound; for y, bottomBound
// If average the shifts on all labels and add them to 0
// TODO: Not sure if should enable it.
// Pros: The angle of lines will distribute more equally
// Cons: In some layout. It may not what user wanted. like in pie. the label of last sector is usually changed unexpectedly.
balanceShift) {
  var len = list.length;
  var xyDim = XY[xyDimIdx];
  var sizeDim = WH[xyDimIdx];
  if (len < 2) {
    return false;
  }
  list.sort(function (a, b) {
    return a.rect[xyDim] - b.rect[xyDim];
  });
  var lastPos = 0;
  var delta;
  var adjusted = false;
  // const shifts = [];
  var totalShifts = 0;
  for (var i = 0; i < len; i++) {
    var item = list[i];
    var rect = item.rect;
    delta = rect[xyDim] - lastPos;
    if (delta < 0) {
      // shiftForward(i, len, -delta);
      rect[xyDim] -= delta;
      item.label[xyDim] -= delta;
      adjusted = true;
    }
    var shift = Math.max(-delta, 0);
    // shifts.push(shift);
    totalShifts += shift;
    lastPos = rect[xyDim] + rect[sizeDim];
  }
  if (totalShifts > 0 && balanceShift) {
    // Shift back to make the distribution more equally.
    shiftList(-totalShifts / len, 0, len);
  }
  // TODO bleedMargin?
  var first = list[0];
  var last = list[len - 1];
  var minGap;
  var maxGap;
  updateMinMaxGap();
  // If ends exceed two bounds, squeeze at most 80%, then take the gap of two bounds.
  minGap < 0 && squeezeGaps(-minGap, 0.8);
  maxGap < 0 && squeezeGaps(maxGap, 0.8);
  updateMinMaxGap();
  takeBoundsGap(minGap, maxGap, 1);
  takeBoundsGap(maxGap, minGap, -1);
  // Handle bailout when there is not enough space.
  updateMinMaxGap();
  if (minGap < 0) {
    squeezeWhenBailout(-minGap);
  }
  if (maxGap < 0) {
    squeezeWhenBailout(maxGap);
  }
  function updateMinMaxGap() {
    minGap = first.rect[xyDim] - minBound;
    maxGap = maxBound - last.rect[xyDim] - last.rect[sizeDim];
  }
  function takeBoundsGap(gapThisBound, gapOtherBound, moveDir) {
    if (gapThisBound < 0) {
      // Move from other gap if can.
      var moveFromMaxGap = Math.min(gapOtherBound, -gapThisBound);
      if (moveFromMaxGap > 0) {
        shiftList(moveFromMaxGap * moveDir, 0, len);
        var remained = moveFromMaxGap + gapThisBound;
        if (remained < 0) {
          squeezeGaps(-remained * moveDir, 1);
        }
      } else {
        squeezeGaps(-gapThisBound * moveDir, 1);
      }
    }
  }
  function shiftList(delta, start, end) {
    if (delta !== 0) {
      adjusted = true;
    }
    for (var i = start; i < end; i++) {
      var item = list[i];
      var rect = item.rect;
      rect[xyDim] += delta;
      item.label[xyDim] += delta;
    }
  }
  // Squeeze gaps if the labels exceed margin.
  function squeezeGaps(delta, maxSqeezePercent) {
    var gaps = [];
    var totalGaps = 0;
    for (var i = 1; i < len; i++) {
      var prevItemRect = list[i - 1].rect;
      var gap = Math.max(list[i].rect[xyDim] - prevItemRect[xyDim] - prevItemRect[sizeDim], 0);
      gaps.push(gap);
      totalGaps += gap;
    }
    if (!totalGaps) {
      return;
    }
    var squeezePercent = Math.min(Math.abs(delta) / totalGaps, maxSqeezePercent);
    if (delta > 0) {
      for (var i = 0; i < len - 1; i++) {
        // Distribute the shift delta to all gaps.
        var movement = gaps[i] * squeezePercent;
        // Forward
        shiftList(movement, 0, i + 1);
      }
    } else {
      // Backward
      for (var i = len - 1; i > 0; i--) {
        // Distribute the shift delta to all gaps.
        var movement = gaps[i - 1] * squeezePercent;
        shiftList(-movement, i, len);
      }
    }
  }
  /**
   * Squeeze to allow overlap if there is no more space available.
   * Let other overlapping strategy like hideOverlap do the job instead of keep exceeding the bounds.
   */
  function squeezeWhenBailout(delta) {
    var dir = delta < 0 ? -1 : 1;
    delta = Math.abs(delta);
    var moveForEachLabel = Math.ceil(delta / (len - 1));
    for (var i = 0; i < len - 1; i++) {
      if (dir > 0) {
        // Forward
        shiftList(moveForEachLabel, 0, i + 1);
      } else {
        // Backward
        shiftList(-moveForEachLabel, len - i - 1, len);
      }
      delta -= moveForEachLabel;
      if (delta <= 0) {
        return;
      }
    }
  }
  return adjusted;
}
/**
 * @see `SavedLabelAttr` in `LabelManager.ts`
 * @see `hideOverlap`
 */
export function restoreIgnore(labelList) {
  for (var i = 0; i < labelList.length; i++) {
    var labelItem = labelList[i];
    var defaultAttr = labelItem.defaultAttr;
    var labelLine = labelItem.labelLine;
    labelItem.label.attr('ignore', defaultAttr.ignore);
    labelLine && labelLine.attr('ignore', defaultAttr.labelGuideIgnore);
  }
}
/**
 * [NOTICE - restore]:
 *  'series:layoutlabels' may be triggered during some EC_PARTIAL_UPDATE passes, such as zooming in series.graph/geo
 *  (`updateLabelLayout`), where the modified `Element` props should be restorable from `defaultAttr`.
 *  @see `SavedLabelAttr` in `LabelManager.ts`
 *  `restoreIgnore` can be called to perform the restore, if needed.
 *
 * [NOTICE - state]:
 *  Regarding Element's states, this method is only designed for the normal state.
 *  PENDING: although currently this method is effectively called in other states in `updateLabelLayout` case,
 *      the bad case is not noticeable in the zooming scenario.
 */
export function hideOverlap(labelList) {
  var displayedLabels = [];
  // TODO, render overflow visible first, put in the displayedLabels.
  labelList.sort(function (a, b) {
    return (b.suggestIgnore ? 1 : 0) - (a.suggestIgnore ? 1 : 0) || b.priority - a.priority;
  });
  function hideEl(el) {
    if (!el.ignore) {
      // Show on emphasis.
      var emphasisState = el.ensureState('emphasis');
      if (emphasisState.ignore == null) {
        emphasisState.ignore = false;
      }
    }
    el.ignore = true;
  }
  for (var i = 0; i < labelList.length; i++) {
    var labelItem = ensureLabelLayoutWithGeometry(labelList[i]);
    // The current `el.ignore` is involved, since some previous overlap
    // resolving strategies may have set `el.ignore` to true.
    if (labelItem.label.ignore) {
      continue;
    }
    var label = labelItem.label;
    var labelLine = labelItem.labelLine;
    // NOTICE: even when the with/height of globalRect of a label is 0, the label line should
    // still be displayed, since we should follow the concept of "truncation", meaning that
    // something exists even if it cannot be fully displayed. A visible label line is necessary
    // to allow users to get a tooltip with label info on hover.
    var overlapped = false;
    for (var j = 0; j < displayedLabels.length; j++) {
      if (labelIntersect(labelItem, displayedLabels[j], null, {
        touchThreshold: 0.05
      })) {
        overlapped = true;
        break;
      }
    }
    // TODO Callback to determine if this overlap should be handled?
    if (overlapped) {
      hideEl(label);
      labelLine && hideEl(labelLine);
    } else {
      displayedLabels.push(labelItem);
    }
  }
}
/**
 * Enable fast check for performance; use obb if inevitable.
 * If `mtv` is used, `targetLayoutInfo` can be moved based on the values filled into `mtv`.
 *
 * This method is based only on the current `Element` states (regardless of other states).
 * Typically this method (and the entire layout process) is performed in normal state.
 */
export function labelIntersect(baseLayoutInfo, targetLayoutInfo, mtv, intersectOpt) {
  if (!baseLayoutInfo || !targetLayoutInfo) {
    return false;
  }
  if (baseLayoutInfo.label && baseLayoutInfo.label.ignore || targetLayoutInfo.label && targetLayoutInfo.label.ignore) {
    return false;
  }
  // Fast rejection.
  if (!baseLayoutInfo.rect.intersect(targetLayoutInfo.rect, mtv, intersectOpt)) {
    return false;
  }
  if (baseLayoutInfo.axisAligned && targetLayoutInfo.axisAligned) {
    return true; // obb is the same as the normal bounding rect.
  }
  return ensureOBB(baseLayoutInfo).intersect(ensureOBB(targetLayoutInfo), mtv, intersectOpt);
}