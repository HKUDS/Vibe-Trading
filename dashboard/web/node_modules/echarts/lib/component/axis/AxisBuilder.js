
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
import { retrieve, defaults, extend, each, isObject, isString, isNumber, isFunction, retrieve2, assert, map, retrieve3, filter } from 'zrender/lib/core/util.js';
import * as graphic from '../../util/graphic.js';
import { getECData } from '../../util/innerStore.js';
import { createTextStyle } from '../../label/labelStyle.js';
import Model from '../../model/Model.js';
import { isRadianAroundZero, remRadian } from '../../util/number.js';
import { createSymbol, normalizeSymbolOffset } from '../../util/symbol.js';
import * as matrixUtil from 'zrender/lib/core/matrix.js';
import { applyTransform as v2ApplyTransform } from 'zrender/lib/core/vector.js';
import { getTickValueOutermost, isNameLocationCenter, shouldShowAllLabels } from '../../coord/axisHelper.js';
import { hideOverlap, labelIntersect, computeLabelGeometry2, ensureLabelLayoutWithGeometry, labelLayoutApplyTranslation, setLabelLayoutDirty, newLabelLayoutWithGeometry } from '../../label/labelLayoutHelper.js';
import { makeInner } from '../../util/model.js';
import { getAxisBreakHelper } from './axisBreakHelper.js';
import { AXIS_BREAK_EXPAND_ACTION_TYPE } from './axisAction.js';
import { getScaleBreakHelper, hasBreaks } from '../../scale/break.js';
import BoundingRect from 'zrender/lib/core/BoundingRect.js';
import Point from 'zrender/lib/core/Point.js';
import { copyTransform } from 'zrender/lib/core/Transformable.js';
import { AxisTickLabelComputingKind, createAxisLabelsComputingContext } from '../../coord/axisTickLabelBuilder.js';
import { isOrdinalScale, isTimeScale } from '../../scale/helper.js';
var PI = Math.PI;
var DEFAULT_CENTER_NAME_MARGIN_LEVELS = [[1, 2, 1, 2], [5, 3, 5, 3], [8, 3, 8, 3]];
var DEFAULT_ENDS_NAME_MARGIN_LEVELS = [[0, 1, 0, 1], [0, 3, 0, 3], [0, 3, 0, 3]];
export var getLabelInner = makeInner();
var getTickInner = makeInner();
/**
 * A context shared by difference axisBuilder instances.
 * For cross-axes overlap resolving.
 *
 * Lifecycle constraint: should not over a pass of ec main process.
 *  If model is changed, the context must be disposed.
 *
 * @see AxisBuilderLocalContext
 */
var AxisBuilderSharedContext = /** @class */function () {
  function AxisBuilderSharedContext(resolveAxisNameOverlap) {
    /**
     * [CAUTION] Do not modify this data structure outside this class.
     */
    this.recordMap = {};
    this.resolveAxisNameOverlap = resolveAxisNameOverlap;
  }
  AxisBuilderSharedContext.prototype.ensureRecord = function (axisModel) {
    var dim = axisModel.axis.dim;
    var idx = axisModel.componentIndex;
    var recordMap = this.recordMap;
    var records = recordMap[dim] || (recordMap[dim] = []);
    return records[idx] || (records[idx] = {
      ready: {}
    });
  };
  return AxisBuilderSharedContext;
}();
export { AxisBuilderSharedContext };
;
/**
 * [CAUTION]
 *  1. The call of this function must be after axisLabel overlap handlings
 *     (such as `hideOverlap`, `fixMinMaxLabelShow`) and after transform calculating.
 *  2. Can be called multiple times and should be idempotent.
 */
function resetOverlapRecordToShared(cfg, shared, axisModel, labelLayoutList) {
  var axis = axisModel.axis;
  var record = shared.ensureRecord(axisModel);
  var labelInfoList = [];
  var stOccupiedRect;
  var useStOccupiedRect = hasAxisName(cfg.axisName) && isNameLocationCenter(cfg.nameLocation);
  each(labelLayoutList, function (layout) {
    var layoutInfo = ensureLabelLayoutWithGeometry(layout);
    if (!layoutInfo || layoutInfo.label.ignore) {
      return;
    }
    labelInfoList.push(layoutInfo);
    var transGroup = record.transGroup;
    if (useStOccupiedRect) {
      // Transform to "standard axis" for creating stOccupiedRect (the label rects union).
      transGroup.transform ? matrixUtil.invert(_stTransTmp, transGroup.transform) : matrixUtil.identity(_stTransTmp);
      if (layoutInfo.transform) {
        matrixUtil.mul(_stTransTmp, _stTransTmp, layoutInfo.transform);
      }
      BoundingRect.copy(_stLabelRectTmp, layoutInfo.localRect);
      _stLabelRectTmp.applyTransform(_stTransTmp);
      stOccupiedRect ? stOccupiedRect.union(_stLabelRectTmp) : BoundingRect.copy(stOccupiedRect = new BoundingRect(0, 0, 0, 0), _stLabelRectTmp);
    }
  });
  var sortByDim = Math.abs(record.dirVec.x) > 0.1 ? 'x' : 'y';
  var sortByValue = record.transGroup[sortByDim];
  labelInfoList.sort(function (info1, info2) {
    return Math.abs(info1.label[sortByDim] - sortByValue) - Math.abs(info2.label[sortByDim] - sortByValue);
  });
  if (useStOccupiedRect && stOccupiedRect) {
    var extent = axis.getExtent();
    var axisLineX = Math.min(extent[0], extent[1]);
    var axisLineWidth = Math.max(extent[0], extent[1]) - axisLineX;
    // If `nameLocation` is 'middle', enlarge axis labels boundingRect to axisLine to avoid bad
    //  case like that axis name is placed in the gap between axis labels and axis line.
    // If only one label exists, the entire band should be occupied for
    // visual consistency, so extent it to [0, canvas width].
    stOccupiedRect.union(new BoundingRect(axisLineX, 0, axisLineWidth, 1));
  }
  record.stOccupiedRect = stOccupiedRect;
  record.labelInfoList = labelInfoList;
}
var _stTransTmp = matrixUtil.create();
var _stLabelRectTmp = new BoundingRect(0, 0, 0, 0);
/**
 * The default resolver does not involve other axes within the same coordinate system.
 */
export var resolveAxisNameOverlapDefault = function (cfg, ctx, axisModel, nameLayoutInfo, nameMoveDirVec, thisRecord) {
  if (isNameLocationCenter(cfg.nameLocation)) {
    var stOccupiedRect = thisRecord.stOccupiedRect;
    if (stOccupiedRect) {
      moveIfOverlap(computeLabelGeometry2({}, stOccupiedRect, thisRecord.transGroup.transform), nameLayoutInfo, nameMoveDirVec);
    }
  } else {
    moveIfOverlapByLinearLabels(thisRecord.labelInfoList, thisRecord.dirVec, nameLayoutInfo, nameMoveDirVec);
  }
};
// [NOTICE] not consider ignore.
function moveIfOverlap(basedLayoutInfo, movableLayoutInfo, moveDirVec) {
  var mtv = new Point();
  if (labelIntersect(basedLayoutInfo, movableLayoutInfo, mtv, {
    direction: Math.atan2(moveDirVec.y, moveDirVec.x),
    bidirectional: false,
    touchThreshold: 0.05
  })) {
    labelLayoutApplyTranslation(movableLayoutInfo, mtv);
  }
}
export function moveIfOverlapByLinearLabels(baseLayoutInfoList, baseDirVec, movableLayoutInfo, moveDirVec) {
  // Detect and move from far to close.
  var sameDir = Point.dot(moveDirVec, baseDirVec) >= 0;
  for (var idx = 0, len = baseLayoutInfoList.length; idx < len; idx++) {
    var labelInfo = baseLayoutInfoList[sameDir ? idx : len - 1 - idx];
    if (!labelInfo.label.ignore) {
      moveIfOverlap(labelInfo, movableLayoutInfo, moveDirVec);
    }
  }
}
/**
 * @caution
 * - Ensure it is called after the data processing stage finished.
 * - It might be called before `CahrtView#render`, sush as called at `CoordinateSystem#update`,
 *  thus ensure the result the same whenever it is called.
 *
 * A builder for a straight-line axis.
 *
 * A final axis is translated and rotated from a "standard axis".
 * So opt.position and opt.rotation is required.
 *
 * A "standard axis" is the axis [0,0]-->[abs(axisExtent[1]-axisExtent[0]),0]
 * for example: [0,0]-->[50,0]
 */
var AxisBuilder = /** @class */function () {
  /**
   * [CAUTION]: axisModel.axis.extent/scale must be ready to use.
   */
  function AxisBuilder(axisModel, api, opt, shared) {
    this.group = new graphic.Group();
    this._axisModel = axisModel;
    this._api = api;
    this._local = {};
    this._shared = shared || new AxisBuilderSharedContext(resolveAxisNameOverlapDefault);
    this._resetCfgDetermined(opt);
  }
  /**
   * Regarding axis label related configurations, only the change of label.x/y is supported; other
   * changes are not necessary and not performant. To be specific, only `axis.position`
   * (and consequently `labelOffset`) and `axis.extent` can be changed, and assume everything in
   * `axisModel` are not changed.
   * Axis line related configurations can be changed since this method can only be called
   * before they are created.
   */
  AxisBuilder.prototype.updateCfg = function (opt) {
    if (process.env.NODE_ENV !== 'production') {
      var ready = this._shared.ensureRecord(this._axisModel).ready;
      // After that, changing cfg is not supported; avoid unnecessary complexity.
      assert(!ready.axisLine && !ready.axisTickLabelDetermine);
      // Have to be called again if cfg changed.
      ready.axisName = ready.axisTickLabelEstimate = false;
    }
    var raw = this._cfg.raw;
    raw.position = opt.position;
    raw.labelOffset = opt.labelOffset;
    this._resetCfgDetermined(raw);
  };
  /**
   * [CAUTION] For debug usage. Never change it outside!
   */
  AxisBuilder.prototype.__getRawCfg = function () {
    return this._cfg.raw;
  };
  AxisBuilder.prototype._resetCfgDetermined = function (raw) {
    var axisModel = this._axisModel;
    // FIXME:
    //  Currently there is no uniformed way to set default values if an option
    //  is specified null/undefined by user (intentionally or unintentionally),
    //  e.g. null/undefined is not a illegal value for `nameLocation`.
    //  Try to use `getDefaultOption` to address it. But radar has no `getDefaultOption`.
    var axisModelDefaultOption = axisModel.getDefaultOption ? axisModel.getDefaultOption() : {};
    // Default value
    var axisName = retrieve2(raw.axisName, axisModel.get('name'));
    var nameMoveOverlapOption = axisModel.get('nameMoveOverlap');
    if (nameMoveOverlapOption == null || nameMoveOverlapOption === 'auto') {
      nameMoveOverlapOption = retrieve2(raw.defaultNameMoveOverlap, true);
    }
    var cfg = {
      raw: raw,
      position: raw.position,
      rotation: raw.rotation,
      nameDirection: retrieve2(raw.nameDirection, 1),
      tickDirection: retrieve2(raw.tickDirection, 1),
      labelDirection: retrieve2(raw.labelDirection, 1),
      labelOffset: retrieve2(raw.labelOffset, 0),
      silent: retrieve2(raw.silent, true),
      axisName: axisName,
      nameLocation: retrieve3(axisModel.get('nameLocation'), axisModelDefaultOption.nameLocation, 'end'),
      shouldNameMoveOverlap: hasAxisName(axisName) && nameMoveOverlapOption,
      optionHideOverlap: axisModel.get(['axisLabel', 'hideOverlap']),
      showMinorTicks: axisModel.get(['minorTick', 'show'])
    };
    if (process.env.NODE_ENV !== 'production') {
      assert(cfg.position != null);
      assert(cfg.rotation != null);
    }
    this._cfg = cfg;
    // FIXME Not use a separate text group?
    var transformGroup = new graphic.Group({
      x: cfg.position[0],
      y: cfg.position[1],
      rotation: cfg.rotation
    });
    transformGroup.updateTransform();
    this._transformGroup = transformGroup;
    var record = this._shared.ensureRecord(axisModel);
    record.transGroup = this._transformGroup;
    record.dirVec = new Point(Math.cos(-cfg.rotation), Math.sin(-cfg.rotation));
  };
  AxisBuilder.prototype.build = function (axisPartNameMap, extraParams) {
    var _this = this;
    if (!axisPartNameMap) {
      axisPartNameMap = {
        axisLine: true,
        axisTickLabelEstimate: false,
        axisTickLabelDetermine: true,
        axisName: true
      };
    }
    each(AXIS_BUILDER_AXIS_PART_NAMES, function (partName) {
      if (axisPartNameMap[partName]) {
        builders[partName](_this._cfg, _this._local, _this._shared, _this._axisModel, _this.group, _this._transformGroup, _this._api, extraParams || {});
      }
    });
    return this;
  };
  /**
   * Currently only get text align/verticalAlign by rotation.
   * NO `position` is involved, otherwise it have to be performed for each `updateAxisLabelChangableProps`.
   */
  AxisBuilder.innerTextLayout = function (axisRotation, textRotation, direction) {
    var rotationDiff = remRadian(textRotation - axisRotation);
    var textAlign;
    var textVerticalAlign;
    if (isRadianAroundZero(rotationDiff)) {
      // Label is parallel with axis line.
      textVerticalAlign = direction > 0 ? 'top' : 'bottom';
      textAlign = 'center';
    } else if (isRadianAroundZero(rotationDiff - PI)) {
      // Label is inverse parallel with axis line.
      textVerticalAlign = direction > 0 ? 'bottom' : 'top';
      textAlign = 'center';
    } else {
      textVerticalAlign = 'middle';
      if (rotationDiff > 0 && rotationDiff < PI) {
        textAlign = direction > 0 ? 'right' : 'left';
      } else {
        textAlign = direction > 0 ? 'left' : 'right';
      }
    }
    return {
      rotation: rotationDiff,
      textAlign: textAlign,
      textVerticalAlign: textVerticalAlign
    };
  };
  AxisBuilder.makeAxisEventDataBase = function (axisModel) {
    var eventData = {
      componentType: axisModel.mainType,
      componentIndex: axisModel.componentIndex
    };
    eventData[axisModel.mainType + 'Index'] = axisModel.componentIndex;
    return eventData;
  };
  AxisBuilder.isLabelSilent = function (axisModel) {
    var tooltipOpt = axisModel.get('tooltip');
    return axisModel.get('silent')
    // Consider mouse cursor, add these restrictions.
    || !(axisModel.get('triggerEvent') || tooltipOpt && tooltipOpt.show);
  };
  return AxisBuilder;
}();
;
// Sorted by dependency order.
var AXIS_BUILDER_AXIS_PART_NAMES = ['axisLine', 'axisTickLabelEstimate', 'axisTickLabelDetermine', 'axisName'];
var builders = {
  axisLine: function (cfg, local, shared, axisModel, group, transformGroup, api) {
    if (process.env.NODE_ENV !== 'production') {
      var ready = shared.ensureRecord(axisModel).ready;
      assert(!ready.axisLine);
      ready.axisLine = true;
    }
    var shown = axisModel.get(['axisLine', 'show']);
    if (shown === 'auto') {
      shown = true;
      if (cfg.raw.axisLineAutoShow != null) {
        shown = !!cfg.raw.axisLineAutoShow;
      }
    }
    if (!shown) {
      return;
    }
    var extent = axisModel.axis.getExtent();
    var matrix = transformGroup.transform;
    var pt1 = [extent[0], 0];
    var pt2 = [extent[1], 0];
    var inverse = pt1[0] > pt2[0];
    if (matrix) {
      v2ApplyTransform(pt1, pt1, matrix);
      v2ApplyTransform(pt2, pt2, matrix);
    }
    var lineStyle = extend({
      lineCap: 'round'
    }, axisModel.getModel(['axisLine', 'lineStyle']).getLineStyle());
    var pathBaseProp = {
      strokeContainThreshold: cfg.raw.strokeContainThreshold || 5,
      silent: true,
      z2: 1,
      style: lineStyle
    };
    if (axisModel.get(['axisLine', 'breakLine']) && hasBreaks(axisModel.axis.scale)) {
      getAxisBreakHelper().buildAxisBreakLine(axisModel, group, transformGroup, pathBaseProp);
    } else {
      var line = new graphic.Line(extend({
        shape: {
          x1: pt1[0],
          y1: pt1[1],
          x2: pt2[0],
          y2: pt2[1]
        }
      }, pathBaseProp));
      graphic.subPixelOptimizeLine(line.shape, line.style.lineWidth);
      line.anid = 'line';
      group.add(line);
    }
    var arrows = axisModel.get(['axisLine', 'symbol']);
    if (arrows != null) {
      var arrowSize = axisModel.get(['axisLine', 'symbolSize']);
      if (isString(arrows)) {
        // Use the same arrow for start and end point
        arrows = [arrows, arrows];
      }
      if (isString(arrowSize) || isNumber(arrowSize)) {
        // Use the same size for width and height
        arrowSize = [arrowSize, arrowSize];
      }
      var arrowOffset = normalizeSymbolOffset(axisModel.get(['axisLine', 'symbolOffset']) || 0, arrowSize);
      var symbolWidth_1 = arrowSize[0];
      var symbolHeight_1 = arrowSize[1];
      each([{
        rotate: cfg.rotation + Math.PI / 2,
        offset: arrowOffset[0],
        r: 0
      }, {
        rotate: cfg.rotation - Math.PI / 2,
        offset: arrowOffset[1],
        r: Math.sqrt((pt1[0] - pt2[0]) * (pt1[0] - pt2[0]) + (pt1[1] - pt2[1]) * (pt1[1] - pt2[1]))
      }], function (point, index) {
        if (arrows[index] !== 'none' && arrows[index] != null) {
          var symbol = createSymbol(arrows[index], -symbolWidth_1 / 2, -symbolHeight_1 / 2, symbolWidth_1, symbolHeight_1, lineStyle.stroke, true);
          // Calculate arrow position with offset
          var r = point.r + point.offset;
          var pt = inverse ? pt2 : pt1;
          symbol.attr({
            rotation: point.rotate,
            x: pt[0] + r * Math.cos(cfg.rotation),
            y: pt[1] - r * Math.sin(cfg.rotation),
            silent: true,
            z2: 11
          });
          group.add(symbol);
        }
      });
    }
  },
  /**
   * [CAUTION] This method can be called multiple times, following the change due to `resetCfg` called
   *  in size measurement. Thus this method should be idempotent, and should be performant.
   */
  axisTickLabelEstimate: function (cfg, local, shared, axisModel, group, transformGroup, api, extraParams) {
    if (process.env.NODE_ENV !== 'production') {
      var ready = shared.ensureRecord(axisModel).ready;
      assert(!ready.axisTickLabelDetermine);
      ready.axisTickLabelEstimate = true;
    }
    var needCallLayout = dealLastTickLabelResultReusable(local, group, extraParams);
    if (needCallLayout) {
      layOutAxisTickLabel(cfg, local, shared, axisModel, group, transformGroup, api, AxisTickLabelComputingKind.estimate);
    }
  },
  /**
   * Finish axis tick label build.
   * Can be only called once.
   */
  axisTickLabelDetermine: function (cfg, local, shared, axisModel, group, transformGroup, api, extraParams) {
    if (process.env.NODE_ENV !== 'production') {
      var ready = shared.ensureRecord(axisModel).ready;
      ready.axisTickLabelDetermine = true;
    }
    var needCallLayout = dealLastTickLabelResultReusable(local, group, extraParams);
    if (needCallLayout) {
      layOutAxisTickLabel(cfg, local, shared, axisModel, group, transformGroup, api, AxisTickLabelComputingKind.determine);
    }
    var ticksEls = buildAxisMajorTicks(cfg, group, transformGroup, axisModel);
    syncLabelIgnoreToMajorTicks(cfg, local.labelLayoutList, ticksEls);
    buildAxisMinorTicks(cfg, group, transformGroup, axisModel, cfg.tickDirection);
  },
  /**
   * [CAUTION] This method can be called multiple times, following the change due to `resetCfg` called
   *  in size measurement. Thus this method should be idempotent, and should be performant.
   */
  axisName: function (cfg, local, shared, axisModel, group, transformGroup, api, extraParams) {
    var sharedRecord = shared.ensureRecord(axisModel);
    if (process.env.NODE_ENV !== 'production') {
      var ready = sharedRecord.ready;
      assert(ready.axisTickLabelEstimate || ready.axisTickLabelDetermine);
      ready.axisName = true;
    }
    // Remove the existing name result created in estimation phase.
    if (local.nameEl) {
      group.remove(local.nameEl);
      local.nameEl = sharedRecord.nameLayout = sharedRecord.nameLocation = null;
    }
    var name = cfg.axisName;
    if (!hasAxisName(name)) {
      return;
    }
    var nameLocation = cfg.nameLocation;
    var nameDirection = cfg.nameDirection;
    var textStyleModel = axisModel.getModel('nameTextStyle');
    var gap = axisModel.get('nameGap') || 0;
    var extent = axisModel.axis.getExtent();
    var gapStartEndSignal = axisModel.axis.inverse ? -1 : 1;
    var pos = new Point(0, 0);
    var nameMoveDirVec = new Point(0, 0);
    if (nameLocation === 'start') {
      pos.x = extent[0] - gapStartEndSignal * gap;
      nameMoveDirVec.x = -gapStartEndSignal;
    } else if (nameLocation === 'end') {
      pos.x = extent[1] + gapStartEndSignal * gap;
      nameMoveDirVec.x = gapStartEndSignal;
    } else {
      // 'middle' or 'center'
      pos.x = (extent[0] + extent[1]) / 2;
      pos.y = cfg.labelOffset + nameDirection * gap;
      nameMoveDirVec.y = nameDirection;
    }
    var mt = matrixUtil.create();
    nameMoveDirVec.transform(matrixUtil.rotate(mt, mt, cfg.rotation));
    var nameRotation = axisModel.get('nameRotate');
    if (nameRotation != null) {
      nameRotation = nameRotation * PI / 180; // To radian.
    }
    var labelLayout;
    var axisNameAvailableWidth;
    if (isNameLocationCenter(nameLocation)) {
      labelLayout = AxisBuilder.innerTextLayout(cfg.rotation, nameRotation != null ? nameRotation : cfg.rotation,
      // Adapt to axis.
      nameDirection);
    } else {
      labelLayout = endTextLayout(cfg.rotation, nameLocation, nameRotation || 0, extent);
      axisNameAvailableWidth = cfg.raw.axisNameAvailableWidth;
      if (axisNameAvailableWidth != null) {
        axisNameAvailableWidth = Math.abs(axisNameAvailableWidth / Math.sin(labelLayout.rotation));
        !isFinite(axisNameAvailableWidth) && (axisNameAvailableWidth = null);
      }
    }
    var textFont = textStyleModel.getFont();
    var truncateOpt = axisModel.get('nameTruncate', true) || {};
    var ellipsis = truncateOpt.ellipsis;
    var maxWidth = retrieve(cfg.raw.nameTruncateMaxWidth, truncateOpt.maxWidth, axisNameAvailableWidth);
    var nameMarginLevel = extraParams.nameMarginLevel || 0;
    var textEl = new graphic.Text({
      x: pos.x,
      y: pos.y,
      rotation: labelLayout.rotation,
      silent: AxisBuilder.isLabelSilent(axisModel),
      style: createTextStyle(textStyleModel, {
        text: name,
        font: textFont,
        overflow: 'truncate',
        width: maxWidth,
        ellipsis: ellipsis,
        fill: textStyleModel.getTextColor() || axisModel.get(['axisLine', 'lineStyle', 'color']),
        align: textStyleModel.get('align') || labelLayout.textAlign,
        verticalAlign: textStyleModel.get('verticalAlign') || labelLayout.textVerticalAlign
      }),
      z2: 1
    });
    graphic.setTooltipConfig({
      el: textEl,
      componentModel: axisModel,
      itemName: name
    });
    textEl.__fullText = name;
    // Id for animation
    textEl.anid = 'name';
    if (axisModel.get('triggerEvent')) {
      var eventData = AxisBuilder.makeAxisEventDataBase(axisModel);
      eventData.targetType = 'axisName';
      eventData.name = name;
      getECData(textEl).eventData = eventData;
    }
    transformGroup.add(textEl);
    textEl.updateTransform();
    local.nameEl = textEl;
    var nameLayout = sharedRecord.nameLayout = ensureLabelLayoutWithGeometry({
      label: textEl,
      priority: textEl.z2,
      defaultAttr: {
        ignore: textEl.ignore
      },
      marginDefault: isNameLocationCenter(nameLocation)
      // Make axis name visually far from axis labels.
      // (but not too aggressive, consider multiple small charts)
      ? DEFAULT_CENTER_NAME_MARGIN_LEVELS[nameMarginLevel]
      // top/button margin is set to `0` to inserted the xAxis name into the indention
      // above the axis labels to save space. (see example below.)
      : DEFAULT_ENDS_NAME_MARGIN_LEVELS[nameMarginLevel]
    });
    sharedRecord.nameLocation = nameLocation;
    group.add(textEl);
    textEl.decomposeTransform();
    if (cfg.shouldNameMoveOverlap && nameLayout) {
      var record = shared.ensureRecord(axisModel);
      if (process.env.NODE_ENV !== 'production') {
        assert(record.labelInfoList);
      }
      shared.resolveAxisNameOverlap(cfg, shared, axisModel, nameLayout, nameMoveDirVec, record);
    }
  }
};
function layOutAxisTickLabel(cfg, local, shared, axisModel, group, transformGroup, api, kind) {
  if (!axisLabelBuildResultExists(local)) {
    buildAxisLabel(cfg, local, group, kind, axisModel, api);
  }
  var labelLayoutList = local.labelLayoutList;
  updateAxisLabelChangableProps(cfg, axisModel, labelLayoutList, transformGroup);
  adjustBreakLabels(axisModel, cfg.rotation, labelLayoutList);
  var optionHideOverlap = cfg.optionHideOverlap;
  fixMinMaxLabelShow(axisModel, labelLayoutList, optionHideOverlap);
  if (optionHideOverlap) {
    // This bit fixes the label overlap issue for the time chart.
    // See https://github.com/apache/echarts/issues/14266 for more.
    hideOverlap(
    // Filter the already ignored labels by the previous overlap resolving methods.
    filter(labelLayoutList, function (layout) {
      return layout && !layout.label.ignore;
    }));
  }
  // Always call it even this axis has no name, since it serves in overlapping detection
  // and grid outerBounds on other axis.
  resetOverlapRecordToShared(cfg, shared, axisModel, labelLayoutList);
}
;
function endTextLayout(rotation, textPosition, textRotate, extent) {
  var rotationDiff = remRadian(textRotate - rotation);
  var textAlign;
  var textVerticalAlign;
  var inverse = extent[0] > extent[1];
  var onLeft = textPosition === 'start' && !inverse || textPosition !== 'start' && inverse;
  if (isRadianAroundZero(rotationDiff - PI / 2)) {
    textVerticalAlign = onLeft ? 'bottom' : 'top';
    textAlign = 'center';
  } else if (isRadianAroundZero(rotationDiff - PI * 1.5)) {
    textVerticalAlign = onLeft ? 'top' : 'bottom';
    textAlign = 'center';
  } else {
    textVerticalAlign = 'middle';
    if (rotationDiff < PI * 1.5 && rotationDiff > PI / 2) {
      textAlign = onLeft ? 'left' : 'right';
    } else {
      textAlign = onLeft ? 'right' : 'left';
    }
  }
  return {
    rotation: rotationDiff,
    textAlign: textAlign,
    textVerticalAlign: textVerticalAlign
  };
}
/**
 * Assume `labelLayoutList` has no `label.ignore: true`.
 * Assume `labelLayoutList` have been sorted by value ascending order.
 */
function fixMinMaxLabelShow(axisModel, labelLayoutList, optionHideOverlap) {
  var axis = axisModel.axis;
  var customValuesOption = axisModel.get(['axisLabel', 'customValues']);
  if (shouldShowAllLabels(axis)) {
    return;
  }
  // FIXME
  // Have not consider onBand yet, where tick els is more than label els.
  // Assert no ignore in labels.
  function deal(showMinMaxLabelOption, outmostLabelIdx, innerLabelIdx) {
    var outmostLabelLayout = ensureLabelLayoutWithGeometry(labelLayoutList[outmostLabelIdx]);
    var innerLabelLayout = ensureLabelLayoutWithGeometry(labelLayoutList[innerLabelIdx]);
    var scale = axis.scale;
    if (!outmostLabelLayout || !innerLabelLayout) {
      return;
    }
    if (showMinMaxLabelOption == null) {
      if (!optionHideOverlap && customValuesOption) {
        // In this case, users are unlikely to expect labels to be hidden.
        return;
      }
      var tick = getLabelInner(outmostLabelLayout.label).labelInfo.tick;
      if (
      // TimeScale does not expand extent to "nice", so eliminate labels that are not nice.
      isTimeScale(scale) && tick.notNice
      // Category axis does not expect tick that out of axisLabel.internal to be displayed
      // unless required.
      || isOrdinalScale(scale) && tick.offInterval) {
        ignoreEl(outmostLabelLayout.label);
        return;
      }
    }
    if (showMinMaxLabelOption === false || outmostLabelLayout.suggestIgnore) {
      ignoreEl(outmostLabelLayout.label);
      return;
    }
    if (innerLabelLayout.suggestIgnore) {
      ignoreEl(innerLabelLayout.label);
      return;
    }
    // PENDING: Originally we thought `optionHideOverlap === false` means do not hide anything,
    //  since currently the bounding rect of text might not accurate enough and might slightly bigger,
    //  which causes false positive. But `optionHideOverlap: null/undfined` is falsy and likely
    //  be treated as false.
    // In most fonts the glyph does not reach the boundary of the bounding rect.
    // This is needed to avoid too aggressive to hide two elements that meet at the edge
    // due to compact layout by the same bounding rect or OBB.
    var touchThreshold = 0.1;
    // This treatment is for backward compatibility. And `!optionHideOverlap` implies that
    // the user accepts the visual touch between adjacent labels, thus "hide min/max label"
    // should be conservative, since the space might be sufficient in this case.
    if (!optionHideOverlap) {
      var marginForce = [0, 0, 0, 0];
      // Make a copy to apply `ignoreMargin`.
      outmostLabelLayout = newLabelLayoutWithGeometry({
        marginForce: marginForce
      }, outmostLabelLayout);
      innerLabelLayout = newLabelLayoutWithGeometry({
        marginForce: marginForce
      }, innerLabelLayout);
    }
    if (labelIntersect(outmostLabelLayout, innerLabelLayout, null, {
      touchThreshold: touchThreshold
    })) {
      if (showMinMaxLabelOption) {
        ignoreEl(innerLabelLayout.label);
      } else {
        ignoreEl(outmostLabelLayout.label);
      }
    }
  }
  // If min or max are user set, we need to check
  // If the tick on min(max) are overlap on their neighbour tick
  // If they are overlapped, we need to hide the min(max) tick label
  var showMinLabelOption = axisModel.get(['axisLabel', 'showMinLabel']);
  var showMaxLabelOption = axisModel.get(['axisLabel', 'showMaxLabel']);
  var labelsLen = labelLayoutList.length;
  deal(showMinLabelOption, 0, 1);
  deal(showMaxLabelOption, labelsLen - 1, labelsLen - 2);
}
// Under default settings, it is visually odd to display a tick without its label,
// since ticks extend from axis line towards labels and serve as visual guide.
// PENDING: Is there opposite cases?
function syncLabelIgnoreToMajorTicks(cfg, labelLayoutList, tickEls) {
  if (cfg.showMinorTicks) {
    // It probably unreasonable to hide major ticks when show minor ticks.
    return;
  }
  each(labelLayoutList, function (labelLayout) {
    if (labelLayout && labelLayout.label.ignore) {
      for (var idx = 0; idx < tickEls.length; idx++) {
        var tickEl = tickEls[idx];
        // Assume small array, linear search is fine for performance.
        // PENDING: measure?
        var tickInner = getTickInner(tickEl);
        var labelInner = getLabelInner(labelLayout.label);
        if (tickInner.tickValue != null && !tickInner.onBand && tickInner.tickValue === labelInner.labelInfo.tick.value) {
          ignoreEl(tickEl);
          return;
        }
      }
    }
  });
}
function ignoreEl(el) {
  el && (el.ignore = true);
}
function createTicks(ticksCoords, tickTransform, tickEndCoord, tickLineStyle, anidPrefix) {
  var tickEls = [];
  var pt1 = [];
  var pt2 = [];
  for (var i = 0; i < ticksCoords.length; i++) {
    var tickCoord = ticksCoords[i].coord;
    pt1[0] = tickCoord;
    pt1[1] = 0;
    pt2[0] = tickCoord;
    pt2[1] = tickEndCoord;
    if (tickTransform) {
      v2ApplyTransform(pt1, pt1, tickTransform);
      v2ApplyTransform(pt2, pt2, tickTransform);
    }
    // Tick line, Not use group transform to have better line draw
    var tickEl = new graphic.Line({
      shape: {
        x1: pt1[0],
        y1: pt1[1],
        x2: pt2[0],
        y2: pt2[1]
      },
      style: tickLineStyle,
      z2: 2,
      autoBatch: true,
      silent: true
    });
    graphic.subPixelOptimizeLine(tickEl.shape, tickEl.style.lineWidth);
    tickEl.anid = anidPrefix + '_' + ticksCoords[i].tickValue;
    tickEls.push(tickEl);
    var inner = getTickInner(tickEl);
    inner.onBand = !!ticksCoords[i].onBand;
    inner.tickValue = ticksCoords[i].tickValue;
  }
  return tickEls;
}
function buildAxisMajorTicks(cfg, group, transformGroup, axisModel) {
  var axis = axisModel.axis;
  var tickModel = axisModel.getModel('axisTick');
  var shown = tickModel.get('show');
  if (shown === 'auto') {
    shown = true;
    if (cfg.raw.axisTickAutoShow != null) {
      shown = !!cfg.raw.axisTickAutoShow;
    }
  }
  if (!shown || axis.scale.isBlank()) {
    return [];
  }
  var lineStyleModel = tickModel.getModel('lineStyle');
  var tickEndCoord = cfg.tickDirection * tickModel.get('length');
  var ticksCoords = axis.getTicksCoords();
  var ticksEls = createTicks(ticksCoords, transformGroup.transform, tickEndCoord, defaults(lineStyleModel.getLineStyle(), {
    stroke: axisModel.get(['axisLine', 'lineStyle', 'color'])
  }), 'ticks');
  for (var i = 0; i < ticksEls.length; i++) {
    group.add(ticksEls[i]);
  }
  return ticksEls;
}
function buildAxisMinorTicks(cfg, group, transformGroup, axisModel, tickDirection) {
  var axis = axisModel.axis;
  var minorTickModel = axisModel.getModel('minorTick');
  if (!cfg.showMinorTicks || axis.scale.isBlank()) {
    return;
  }
  var minorTicksCoords = axis.getMinorTicksCoords();
  if (!minorTicksCoords.length) {
    return;
  }
  var lineStyleModel = minorTickModel.getModel('lineStyle');
  var tickEndCoord = tickDirection * minorTickModel.get('length');
  var minorTickLineStyle = defaults(lineStyleModel.getLineStyle(), defaults(axisModel.getModel('axisTick').getLineStyle(), {
    stroke: axisModel.get(['axisLine', 'lineStyle', 'color'])
  }));
  for (var i = 0; i < minorTicksCoords.length; i++) {
    var minorTicksEls = createTicks(minorTicksCoords[i], transformGroup.transform, tickEndCoord, minorTickLineStyle, 'minorticks_' + i);
    for (var k = 0; k < minorTicksEls.length; k++) {
      group.add(minorTicksEls[k]);
    }
  }
}
// Return whether need to call `layOutAxisTickLabel` again.
function dealLastTickLabelResultReusable(local, group, extraParams) {
  if (axisLabelBuildResultExists(local)) {
    var axisLabelsCreationContext = local.axisLabelsCreationContext;
    if (process.env.NODE_ENV !== 'production') {
      assert(local.labelGroup && axisLabelsCreationContext);
    }
    var noPxChangeTryDetermine = axisLabelsCreationContext.out.noPxChangeTryDetermine;
    if (extraParams.noPxChange) {
      var canDetermine = true;
      for (var idx = 0; idx < noPxChangeTryDetermine.length; idx++) {
        canDetermine = canDetermine && noPxChangeTryDetermine[idx]();
      }
      if (canDetermine) {
        return false;
      }
    }
    if (noPxChangeTryDetermine.length) {
      // Remove the result of `buildAxisLabel`
      group.remove(local.labelGroup);
      axisLabelBuildResultSet(local, null, null, null);
    }
  }
  return true;
}
function buildAxisLabel(cfg, local, group, kind, axisModel, api) {
  var axis = axisModel.axis;
  var show = retrieve(cfg.raw.axisLabelShow, axisModel.get(['axisLabel', 'show']));
  var labelGroup = new graphic.Group();
  group.add(labelGroup);
  var axisLabelCreationCtx = createAxisLabelsComputingContext(kind);
  if (!show || axis.scale.isBlank()) {
    axisLabelBuildResultSet(local, [], labelGroup, axisLabelCreationCtx);
    return;
  }
  var labelModel = axisModel.getModel('axisLabel');
  var labels = axis.getViewLabels(axisLabelCreationCtx);
  // Special label rotate.
  var labelRotation = (retrieve(cfg.raw.labelRotate, labelModel.get('rotate')) || 0) * PI / 180;
  var labelLayout = AxisBuilder.innerTextLayout(cfg.rotation, labelRotation, cfg.labelDirection);
  var rawCategoryData = axisModel.getCategories && axisModel.getCategories(true);
  var labelEls = [];
  var triggerEvent = axisModel.get('triggerEvent');
  var z2Min = Infinity;
  var z2Max = -Infinity;
  each(labels, function (labelItem, index) {
    var _a;
    var labelItemTick = labelItem.tick;
    var formattedLabel = labelItem.formattedLabel;
    var rawLabel = labelItem.rawLabel;
    var itemLabelModel = labelModel;
    var tickValue = getTickValueOutermost(axis.scale, labelItemTick);
    if (rawCategoryData && rawCategoryData[tickValue]) {
      var rawCategoryItem = rawCategoryData[tickValue];
      if (isObject(rawCategoryItem) && rawCategoryItem.textStyle) {
        itemLabelModel = new Model(rawCategoryItem.textStyle, labelModel, axisModel.ecModel);
      }
    }
    var textColor = itemLabelModel.getTextColor() || axisModel.get(['axisLine', 'lineStyle', 'color']);
    var align = itemLabelModel.getShallow('align', true) || labelLayout.textAlign;
    var alignMin = retrieve2(itemLabelModel.getShallow('alignMinLabel', true), align);
    var alignMax = retrieve2(itemLabelModel.getShallow('alignMaxLabel', true), align);
    var verticalAlign = itemLabelModel.getShallow('verticalAlign', true) || itemLabelModel.getShallow('baseline', true) || labelLayout.textVerticalAlign;
    var verticalAlignMin = retrieve2(itemLabelModel.getShallow('verticalAlignMinLabel', true), verticalAlign);
    var verticalAlignMax = retrieve2(itemLabelModel.getShallow('verticalAlignMaxLabel', true), verticalAlign);
    var z2 = 10 + (((_a = labelItemTick.time) === null || _a === void 0 ? void 0 : _a.level) || 0);
    z2Min = Math.min(z2Min, z2);
    z2Max = Math.max(z2Max, z2);
    var textEl = new graphic.Text({
      // --- transform props start ---
      // All of the transform props MUST not be set here, but should be set in
      // `updateAxisLabelChangableProps`, because they may change in estimation,
      // and need to calculate based on global coord sys by `decomposeTransform`.
      x: 0,
      y: 0,
      rotation: 0,
      // --- transform props end ---
      silent: AxisBuilder.isLabelSilent(axisModel),
      z2: z2,
      style: createTextStyle(itemLabelModel, {
        text: formattedLabel,
        align: index === 0 ? alignMin : index === labels.length - 1 ? alignMax : align,
        verticalAlign: index === 0 ? verticalAlignMin : index === labels.length - 1 ? verticalAlignMax : verticalAlign,
        fill: isFunction(textColor) ? textColor(
        // (1) In category axis with data zoom, tick is not the original
        // index of axis.data. So tick should not be exposed to user
        // in category axis.
        // (2) Compatible with previous version, which always use formatted label as
        // input. But in interval scale the formatted label is like '223,445', which
        // maked user replace ','. So we modify it to return original val but remain
        // it as 'string' to avoid error in replacing.
        axis.type === 'category' ? rawLabel : axis.type === 'value' ? tickValue + '' : tickValue, index) : textColor
      })
    });
    textEl.anid = 'label_' + tickValue;
    var inner = getLabelInner(textEl);
    inner.labelInfo = labelItem;
    inner.layoutRotation = labelLayout.rotation;
    graphic.setTooltipConfig({
      el: textEl,
      componentModel: axisModel,
      itemName: formattedLabel,
      formatterParamsExtra: {
        isTruncated: function () {
          return textEl.isTruncated;
        },
        value: rawLabel,
        tickIndex: index
      }
    });
    // Pack data for mouse event
    if (triggerEvent) {
      var eventData = AxisBuilder.makeAxisEventDataBase(axisModel);
      eventData.targetType = 'axisLabel';
      eventData.value = rawLabel;
      eventData.tickIndex = index;
      var labelItemTickBreak = labelItem.tick["break"];
      if (labelItemTickBreak) {
        var labelItemTickBreakParsedBreak = labelItemTickBreak.parsedBreak;
        eventData["break"] = {
          // type: labelItem.break.type,
          start: labelItemTickBreakParsedBreak.vmin,
          end: labelItemTickBreakParsedBreak.vmax
        };
      }
      if (axis.type === 'category') {
        eventData.dataIndex = tickValue;
      }
      getECData(textEl).eventData = eventData;
      if (labelItemTickBreak) {
        addBreakEventHandler(axisModel, api, textEl, labelItemTickBreak);
      }
    }
    labelEls.push(textEl);
    labelGroup.add(textEl);
  });
  var labelLayoutList = map(labelEls, function (label) {
    return {
      label: label,
      priority: getLabelInner(label).labelInfo.tick["break"] ? label.z2 + (z2Max - z2Min + 1) // Make break labels be highest priority.
      : label.z2,
      defaultAttr: {
        ignore: label.ignore
      }
    };
  });
  axisLabelBuildResultSet(local, labelLayoutList, labelGroup, axisLabelCreationCtx);
}
// Indicate that `layOutAxisTickLabel` has been called.
function axisLabelBuildResultExists(local) {
  return !!local.labelLayoutList;
}
function axisLabelBuildResultSet(local, labelLayoutList, labelGroup, axisLabelsCreationContext) {
  // Ensure the same lifetime.
  local.labelLayoutList = labelLayoutList;
  local.labelGroup = labelGroup;
  local.axisLabelsCreationContext = axisLabelsCreationContext;
}
function updateAxisLabelChangableProps(cfg, axisModel, labelLayoutList, transformGroup) {
  var labelMargin = axisModel.get(['axisLabel', 'margin']);
  each(labelLayoutList, function (layout, idx) {
    var geometry = ensureLabelLayoutWithGeometry(layout);
    if (!geometry) {
      return;
    }
    var labelEl = geometry.label;
    var inner = getLabelInner(labelEl);
    // See the comment in `suggestIgnore`.
    geometry.suggestIgnore = labelEl.ignore;
    // Currently no `ignore:true` is set in `buildAxisLabel`
    // But `ignore:true` may be set subsequently for overlap handling, thus reset it here.
    labelEl.ignore = false;
    copyTransform(_tmpLayoutEl, _tmpLayoutElReset);
    var axis = axisModel.axis;
    _tmpLayoutEl.x = axis.dataToCoord(getTickValueOutermost(axis.scale, inner.labelInfo.tick));
    _tmpLayoutEl.y = cfg.labelOffset + cfg.labelDirection * labelMargin;
    _tmpLayoutEl.rotation = inner.layoutRotation;
    transformGroup.add(_tmpLayoutEl);
    _tmpLayoutEl.updateTransform();
    transformGroup.remove(_tmpLayoutEl);
    _tmpLayoutEl.decomposeTransform();
    copyTransform(labelEl, _tmpLayoutEl);
    labelEl.markRedraw();
    setLabelLayoutDirty(geometry, true);
    ensureLabelLayoutWithGeometry(geometry);
  });
}
var _tmpLayoutEl = new graphic.Rect();
var _tmpLayoutElReset = new graphic.Rect();
function hasAxisName(axisName) {
  return !!axisName;
}
function addBreakEventHandler(axisModel, api, textEl, visualBreak) {
  textEl.on('click', function (params) {
    var payload = {
      type: AXIS_BREAK_EXPAND_ACTION_TYPE,
      breaks: [{
        start: visualBreak.parsedBreak.breakOption.start,
        end: visualBreak.parsedBreak.breakOption.end
      }]
    };
    payload[axisModel.axis.dim + "AxisIndex"] = axisModel.componentIndex;
    api.dispatchAction(payload);
  });
}
function adjustBreakLabels(axisModel, axisRotation, labelLayoutList) {
  var scaleBreakHelper = getScaleBreakHelper();
  if (!scaleBreakHelper) {
    return;
  }
  var breakLabelIndexPairs = scaleBreakHelper.retrieveAxisBreakPairs(labelLayoutList, function (layoutInfo) {
    return layoutInfo && getLabelInner(layoutInfo.label).labelInfo.tick["break"];
  }, true);
  var moveOverlap = axisModel.get(['breakLabelLayout', 'moveOverlap'], true);
  if (moveOverlap === true || moveOverlap === 'auto') {
    each(breakLabelIndexPairs, function (idxPair) {
      getAxisBreakHelper().adjustBreakLabelPair(axisModel.axis.inverse, axisRotation, [ensureLabelLayoutWithGeometry(labelLayoutList[idxPair[0]]), ensureLabelLayoutWithGeometry(labelLayoutList[idxPair[1]])]);
    });
  }
}
export default AxisBuilder;