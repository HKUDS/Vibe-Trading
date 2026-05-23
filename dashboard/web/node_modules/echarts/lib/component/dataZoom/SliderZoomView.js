
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
import { bind, each, isFunction, isString, indexOf } from 'zrender/lib/core/util.js';
import * as eventTool from 'zrender/lib/core/event.js';
import * as graphic from '../../util/graphic.js';
import * as throttle from '../../util/throttle.js';
import DataZoomView from './DataZoomView.js';
import { linearMap, asc, parsePercent, round } from '../../util/number.js';
import * as layout from '../../util/layout.js';
import sliderMove from '../helper/sliderMove.js';
import { getAxisMainType, collectReferCoordSysModelInfo, getAlignTo } from './helper.js';
import { enableHoverEmphasis } from '../../util/states.js';
import { createSymbol, symbolBuildProxies } from '../../util/symbol.js';
import { deprecateLog } from '../../util/log.js';
import { createTextStyle } from '../../label/labelStyle.js';
import tokens from '../../visual/tokens.js';
import { isOrdinalScale, isTimeScale } from '../../scale/helper.js';
var Rect = graphic.Rect;
// Constants
var DEFAULT_FRAME_BORDER_WIDTH = 1;
var DEFAULT_FILLER_SIZE = 30;
var DEFAULT_MOVE_HANDLE_SIZE = 7;
var HORIZONTAL = 'horizontal';
var VERTICAL = 'vertical';
var LABEL_GAP = 5;
var SHOW_DATA_SHADOW_SERIES_TYPE = ['line', 'bar', 'candlestick', 'scatter'];
var REALTIME_ANIMATION_CONFIG = {
  easing: 'cubicOut',
  duration: 100,
  delay: 0
};
var SliderZoomView = /** @class */function (_super) {
  __extends(SliderZoomView, _super);
  function SliderZoomView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = SliderZoomView.type;
    _this._displayables = {};
    return _this;
  }
  SliderZoomView.prototype.init = function (ecModel, api) {
    this.api = api;
    // A unique handler for each dataZoom component
    this._onBrush = bind(this._onBrush, this);
    this._onBrushEnd = bind(this._onBrushEnd, this);
  };
  SliderZoomView.prototype.render = function (dataZoomModel, ecModel, api, payload) {
    _super.prototype.render.apply(this, arguments);
    throttle.createOrUpdate(this, '_dispatchZoomAction', dataZoomModel.get('throttle'), 'fixRate');
    this._orient = dataZoomModel.getOrient();
    if (dataZoomModel.get('show') === false) {
      this.group.removeAll();
      return;
    }
    if (dataZoomModel.noTarget()) {
      this._clear();
      this.group.removeAll();
      return;
    }
    // Notice: this._resetInterval() should not be executed when payload.type
    // is 'dataZoom', origin this._range should be maintained, otherwise 'pan'
    // or 'zoom' info will be missed because of 'throttle' of this.dispatchAction,
    if (!payload || payload.type !== 'dataZoom' || payload.from !== this.uid) {
      this._buildView();
    }
    this._updateView();
  };
  SliderZoomView.prototype.dispose = function () {
    this._clear();
    _super.prototype.dispose.apply(this, arguments);
  };
  SliderZoomView.prototype._clear = function () {
    throttle.clear(this, '_dispatchZoomAction');
    var zr = this.api.getZr();
    zr.off('mousemove', this._onBrush);
    zr.off('mouseup', this._onBrushEnd);
  };
  SliderZoomView.prototype._buildView = function () {
    var thisGroup = this.group;
    thisGroup.removeAll();
    this._brushing = false;
    this._displayables.brushRect = null;
    this._resetLocation();
    this._resetInterval();
    var barGroup = this._displayables.sliderGroup = new graphic.Group();
    this._renderBackground();
    this._renderHandle();
    this._renderDataShadow();
    thisGroup.add(barGroup);
    this._positionGroup();
  };
  SliderZoomView.prototype._resetLocation = function () {
    var dataZoomModel = this.dataZoomModel;
    var api = this.api;
    var showMoveHandle = dataZoomModel.get('brushSelect');
    var moveHandleSize = showMoveHandle ? DEFAULT_MOVE_HANDLE_SIZE : 0;
    var refContainer = layout.createBoxLayoutReference(dataZoomModel, api).refContainer;
    // If some of x/y/width/height are not specified,
    // auto-adapt according to target grid.
    var coordRect = this._findCoordRect();
    var edgeGap = dataZoomModel.get('defaultLocationEdgeGap', true) || 0;
    // Default align by coordinate system rect.
    var positionInfo = this._orient === HORIZONTAL ? {
      // Why using 'right', because right should be used in vertical,
      // and it is better to be consistent for dealing with position param merge.
      right: refContainer.width - coordRect.x - coordRect.width,
      top: refContainer.height - DEFAULT_FILLER_SIZE - edgeGap - moveHandleSize,
      width: coordRect.width,
      height: DEFAULT_FILLER_SIZE
    } : {
      right: edgeGap,
      top: coordRect.y,
      width: DEFAULT_FILLER_SIZE,
      height: coordRect.height
    };
    // Do not write back to option and replace value 'ph', because
    // the 'ph' value should be recalculated when resize.
    var layoutParams = layout.getLayoutParams(dataZoomModel.option);
    // Replace the placeholder value.
    each(['right', 'top', 'width', 'height'], function (name) {
      if (layoutParams[name] === 'ph') {
        layoutParams[name] = positionInfo[name];
      }
    });
    var layoutRect = layout.getLayoutRect(layoutParams, refContainer);
    this._location = {
      x: layoutRect.x,
      y: layoutRect.y
    };
    this._size = [layoutRect.width, layoutRect.height];
    this._orient === VERTICAL && this._size.reverse();
  };
  SliderZoomView.prototype._positionGroup = function () {
    var thisGroup = this.group;
    var location = this._location;
    var orient = this._orient;
    // Just use the first axis to determine mapping.
    var targetAxisModel = this.dataZoomModel.getFirstTargetAxisModel();
    var inverse = targetAxisModel && targetAxisModel.get('inverse');
    var sliderGroup = this._displayables.sliderGroup;
    var otherAxisInverse = (this._dataShadowInfo || {}).otherAxisInverse;
    // Transform barGroup.
    sliderGroup.attr(orient === HORIZONTAL && !inverse ? {
      scaleY: otherAxisInverse ? 1 : -1,
      scaleX: 1
    } : orient === HORIZONTAL && inverse ? {
      scaleY: otherAxisInverse ? 1 : -1,
      scaleX: -1
    } : orient === VERTICAL && !inverse ? {
      scaleY: otherAxisInverse ? -1 : 1,
      scaleX: 1,
      rotation: Math.PI / 2
    }
    // Don't use Math.PI, considering shadow direction.
    : {
      scaleY: otherAxisInverse ? -1 : 1,
      scaleX: -1,
      rotation: Math.PI / 2
    });
    // Position barGroup
    var rect = thisGroup.getBoundingRect([sliderGroup]);
    var rectX = isNaN(rect.x) ? 0 : rect.x;
    var rectY = isNaN(rect.y) ? 0 : rect.y;
    thisGroup.x = location.x - rectX;
    thisGroup.y = location.y - rectY;
    thisGroup.markRedraw();
  };
  SliderZoomView.prototype._getViewExtent = function () {
    return [0, this._size[0]];
  };
  SliderZoomView.prototype._renderBackground = function () {
    var dataZoomModel = this.dataZoomModel;
    var size = this._size;
    var barGroup = this._displayables.sliderGroup;
    var brushSelect = dataZoomModel.get('brushSelect');
    barGroup.add(new Rect({
      silent: true,
      shape: {
        x: 0,
        y: 0,
        width: size[0],
        height: size[1]
      },
      style: {
        fill: dataZoomModel.get('backgroundColor')
      },
      z2: -40
    }));
    // Click panel, over shadow, below handles.
    var clickPanel = new Rect({
      shape: {
        x: 0,
        y: 0,
        width: size[0],
        height: size[1]
      },
      style: {
        fill: 'transparent'
      },
      z2: 0,
      onclick: bind(this._onClickPanel, this)
    });
    var zr = this.api.getZr();
    if (brushSelect) {
      clickPanel.on('mousedown', this._onBrushStart, this);
      clickPanel.cursor = 'crosshair';
      zr.on('mousemove', this._onBrush);
      zr.on('mouseup', this._onBrushEnd);
    } else {
      zr.off('mousemove', this._onBrush);
      zr.off('mouseup', this._onBrushEnd);
    }
    barGroup.add(clickPanel);
  };
  SliderZoomView.prototype._renderDataShadow = function () {
    var info = this._dataShadowInfo = this._prepareDataShadowInfo();
    this._displayables.dataShadowSegs = [];
    if (!info) {
      return;
    }
    var size = this._size;
    var oldSize = this._shadowSize || [];
    var seriesModel = info.series;
    var data = seriesModel.getRawData();
    var candlestickDim = seriesModel.getShadowDim && seriesModel.getShadowDim();
    var otherDim = candlestickDim && data.getDimensionInfo(candlestickDim) ? seriesModel.getShadowDim() // @see candlestick
    : info.otherDim;
    if (otherDim == null) {
      return;
    }
    var polygonPts = this._shadowPolygonPts;
    var polylinePts = this._shadowPolylinePts;
    // Not re-render if data doesn't change.
    if (data !== this._shadowData || otherDim !== this._shadowDim || size[0] !== oldSize[0] || size[1] !== oldSize[1]) {
      var thisDataExtent_1 = data.getDataExtent(info.thisDim);
      var otherDataExtent_1 = data.getDataExtent(otherDim);
      // Nice extent.
      var otherOffset = (otherDataExtent_1[1] - otherDataExtent_1[0]) * 0.3;
      otherDataExtent_1 = [otherDataExtent_1[0] - otherOffset, otherDataExtent_1[1] + otherOffset];
      var otherShadowExtent_1 = [0, size[1]];
      var thisShadowExtent = [0, size[0]];
      var areaPoints_1 = [[size[0], 0], [0, 0]];
      var linePoints_1 = [];
      var step_1 = thisShadowExtent[1] / Math.max(1, data.count() - 1);
      var normalizationConstant_1 = size[0] / (thisDataExtent_1[1] - thisDataExtent_1[0]);
      var isTimeAxis_1 = info.thisAxis.type === 'time';
      var thisCoord_1 = -step_1;
      // Optimize for large data shadow
      var stride_1 = Math.round(data.count() / size[0]);
      var lastIsEmpty_1;
      data.each([info.thisDim, otherDim], function (thisValue, otherValue, index) {
        if (stride_1 > 0 && index % stride_1) {
          if (!isTimeAxis_1) {
            thisCoord_1 += step_1;
          }
          return;
        }
        thisCoord_1 = isTimeAxis_1 ? (+thisValue - thisDataExtent_1[0]) * normalizationConstant_1 : thisCoord_1 + step_1;
        // FIXME
        // Should consider axis.min/axis.max when drawing dataShadow.
        // FIXME
        // 应该使用统一的空判断？还是在list里进行空判断？
        var isEmpty = otherValue == null || isNaN(otherValue) || otherValue === '';
        // See #4235.
        var otherCoord = isEmpty ? 0 : linearMap(otherValue, otherDataExtent_1, otherShadowExtent_1, true);
        // Attempt to draw data shadow precisely when there are empty value.
        if (isEmpty && !lastIsEmpty_1 && index) {
          areaPoints_1.push([areaPoints_1[areaPoints_1.length - 1][0], 0]);
          linePoints_1.push([linePoints_1[linePoints_1.length - 1][0], 0]);
        } else if (!isEmpty && lastIsEmpty_1) {
          areaPoints_1.push([thisCoord_1, 0]);
          linePoints_1.push([thisCoord_1, 0]);
        }
        if (!isEmpty) {
          areaPoints_1.push([thisCoord_1, otherCoord]);
          linePoints_1.push([thisCoord_1, otherCoord]);
        }
        lastIsEmpty_1 = isEmpty;
      });
      polygonPts = this._shadowPolygonPts = areaPoints_1;
      polylinePts = this._shadowPolylinePts = linePoints_1;
    }
    this._shadowData = data;
    this._shadowDim = otherDim;
    this._shadowSize = [size[0], size[1]];
    var dataZoomModel = this.dataZoomModel;
    function createDataShadowGroup(isSelectedArea) {
      var model = dataZoomModel.getModel(isSelectedArea ? 'selectedDataBackground' : 'dataBackground');
      var group = new graphic.Group();
      var polygon = new graphic.Polygon({
        shape: {
          points: polygonPts
        },
        segmentIgnoreThreshold: 1,
        style: model.getModel('areaStyle').getAreaStyle(),
        silent: true,
        z2: -20
      });
      var polyline = new graphic.Polyline({
        shape: {
          points: polylinePts
        },
        segmentIgnoreThreshold: 1,
        style: model.getModel('lineStyle').getLineStyle(),
        silent: true,
        z2: -19
      });
      group.add(polygon);
      group.add(polyline);
      return group;
    }
    // let dataBackgroundModel = dataZoomModel.getModel('dataBackground');
    for (var i = 0; i < 3; i++) {
      var group = createDataShadowGroup(i === 1);
      this._displayables.sliderGroup.add(group);
      this._displayables.dataShadowSegs.push(group);
    }
  };
  SliderZoomView.prototype._prepareDataShadowInfo = function () {
    var dataZoomModel = this.dataZoomModel;
    var showDataShadow = dataZoomModel.get('showDataShadow');
    if (showDataShadow === false) {
      return;
    }
    // Find a representative series.
    var result;
    var ecModel = this.ecModel;
    dataZoomModel.eachTargetAxis(function (axisDim, axisIndex) {
      var seriesModels = dataZoomModel.getAxisProxy(axisDim, axisIndex).getTargetSeriesModels();
      each(seriesModels, function (seriesModel) {
        if (result) {
          return;
        }
        if (showDataShadow !== true && indexOf(SHOW_DATA_SHADOW_SERIES_TYPE, seriesModel.get('type')) < 0) {
          return;
        }
        var thisAxis = ecModel.getComponent(getAxisMainType(axisDim), axisIndex).axis;
        var otherDim = getOtherDim(axisDim);
        var otherAxisInverse;
        var coordSys = seriesModel.coordinateSystem;
        if (otherDim != null && coordSys.getOtherAxis) {
          otherAxisInverse = coordSys.getOtherAxis(thisAxis).inverse;
        }
        otherDim = seriesModel.getData().mapDimension(otherDim);
        var thisDim = seriesModel.getData().mapDimension(axisDim);
        result = {
          thisAxis: thisAxis,
          series: seriesModel,
          thisDim: thisDim,
          otherDim: otherDim,
          otherAxisInverse: otherAxisInverse
        };
      }, this);
    }, this);
    return result;
  };
  SliderZoomView.prototype._renderHandle = function () {
    var thisGroup = this.group;
    var displayables = this._displayables;
    var handles = displayables.handles = [null, null];
    var handleLabels = displayables.handleLabels = [null, null];
    var sliderGroup = this._displayables.sliderGroup;
    var size = this._size;
    var dataZoomModel = this.dataZoomModel;
    var api = this.api;
    var borderRadius = dataZoomModel.get('borderRadius') || 0;
    var brushSelect = dataZoomModel.get('brushSelect');
    var filler = displayables.filler = new Rect({
      silent: brushSelect,
      style: {
        fill: dataZoomModel.get('fillerColor')
      },
      textConfig: {
        position: 'inside'
      }
    });
    sliderGroup.add(filler);
    // Frame border.
    sliderGroup.add(new Rect({
      silent: true,
      subPixelOptimize: true,
      shape: {
        x: 0,
        y: 0,
        width: size[0],
        height: size[1],
        r: borderRadius
      },
      style: {
        // deprecated option
        stroke: dataZoomModel.get('dataBackgroundColor') || dataZoomModel.get('borderColor'),
        lineWidth: DEFAULT_FRAME_BORDER_WIDTH,
        fill: tokens.color.transparent
      }
    }));
    // Left and right handle to resize
    each([0, 1], function (handleIndex) {
      var iconStr = dataZoomModel.get('handleIcon');
      if (!symbolBuildProxies[iconStr] && iconStr.indexOf('path://') < 0 && iconStr.indexOf('image://') < 0) {
        // Compatitable with the old icon parsers. Which can use a path string without path://
        iconStr = 'path://' + iconStr;
        if (process.env.NODE_ENV !== 'production') {
          deprecateLog('handleIcon now needs \'path://\' prefix when using a path string');
        }
      }
      var path = createSymbol(iconStr, -1, 0, 2, 2, null, true);
      path.attr({
        cursor: getCursor(this._orient),
        draggable: true,
        drift: bind(this._onDragMove, this, handleIndex),
        ondragend: bind(this._onDragEnd, this),
        onmouseover: bind(this._onOverDataInfoTriggerArea, this, true),
        onmouseout: bind(this._onOverDataInfoTriggerArea, this, false),
        z2: 5
      });
      var bRect = path.getBoundingRect();
      var handleSize = dataZoomModel.get('handleSize');
      this._handleHeight = parsePercent(handleSize, this._size[1]);
      this._handleWidth = bRect.width / bRect.height * this._handleHeight;
      path.setStyle(dataZoomModel.getModel('handleStyle').getItemStyle());
      path.style.strokeNoScale = true;
      path.rectHover = true;
      path.ensureState('emphasis').style = dataZoomModel.getModel(['emphasis', 'handleStyle']).getItemStyle();
      enableHoverEmphasis(path);
      var handleColor = dataZoomModel.get('handleColor'); // deprecated option
      // Compatitable with previous version
      if (handleColor != null) {
        path.style.fill = handleColor;
      }
      sliderGroup.add(handles[handleIndex] = path);
      var textStyleModel = dataZoomModel.getModel('textStyle');
      var handleLabel = dataZoomModel.get('handleLabel') || {};
      var handleLabelShow = handleLabel.show || false;
      thisGroup.add(handleLabels[handleIndex] = new graphic.Text({
        silent: true,
        invisible: !handleLabelShow,
        style: createTextStyle(textStyleModel, {
          x: 0,
          y: 0,
          text: '',
          verticalAlign: 'middle',
          align: 'center',
          fill: textStyleModel.getTextColor(),
          font: textStyleModel.getFont()
        }),
        z2: 10
      }));
    }, this);
    // Handle to move. Only visible when brushSelect is set true.
    var actualMoveZone = filler;
    if (brushSelect) {
      var moveHandleHeight = parsePercent(dataZoomModel.get('moveHandleSize'), size[1]);
      var moveHandle_1 = displayables.moveHandle = new graphic.Rect({
        style: dataZoomModel.getModel('moveHandleStyle').getItemStyle(),
        silent: true,
        shape: {
          r: [0, 0, 2, 2],
          y: size[1] - 0.5,
          height: moveHandleHeight
        }
      });
      var iconSize = moveHandleHeight * 0.8;
      var moveHandleIcon = displayables.moveHandleIcon = createSymbol(dataZoomModel.get('moveHandleIcon'), -iconSize / 2, -iconSize / 2, iconSize, iconSize, tokens.color.neutral00, true);
      moveHandleIcon.silent = true;
      moveHandleIcon.y = size[1] + moveHandleHeight / 2 - 0.5;
      moveHandle_1.ensureState('emphasis').style = dataZoomModel.getModel(['emphasis', 'moveHandleStyle']).getItemStyle();
      var moveZoneExpandSize = Math.min(size[1] / 2, Math.max(moveHandleHeight, 10));
      actualMoveZone = displayables.moveZone = new graphic.Rect({
        invisible: true,
        shape: {
          y: size[1] - moveZoneExpandSize,
          height: moveHandleHeight + moveZoneExpandSize
        }
      });
      actualMoveZone.on('mouseover', function () {
        api.enterEmphasis(moveHandle_1);
      }).on('mouseout', function () {
        api.leaveEmphasis(moveHandle_1);
      });
      sliderGroup.add(moveHandle_1);
      sliderGroup.add(moveHandleIcon);
      sliderGroup.add(actualMoveZone);
    }
    actualMoveZone.attr({
      draggable: true,
      cursor: 'grab',
      drift: bind(this._onActualMoveZoneDrift, this),
      ondragstart: bind(this._onActualMoveZoneDragStart, this),
      ondragend: bind(this._onActualMoveZoneDragEnd, this),
      onmouseover: bind(this._onOverDataInfoTriggerArea, this, true),
      onmouseout: bind(this._onOverDataInfoTriggerArea, this, false)
    });
  };
  SliderZoomView.prototype._resetInterval = function () {
    var range = this._range = this.dataZoomModel.getPercentRange();
    var viewExtent = this._getViewExtent();
    this._handleEnds = [linearMap(range[0], [0, 100], viewExtent, true), linearMap(range[1], [0, 100], viewExtent, true)];
  };
  SliderZoomView.prototype._updateInterval = function (handleIndex, delta) {
    var dataZoomModel = this.dataZoomModel;
    var handleEnds = this._handleEnds;
    var viewExtend = this._getViewExtent();
    var minMaxSpan = dataZoomModel.findRepresentativeAxisProxy().getMinMaxSpan();
    var percentExtent = [0, 100];
    sliderMove(delta, handleEnds, viewExtend, dataZoomModel.get('zoomLock') ? 'all' : handleIndex, minMaxSpan.minSpan != null ? linearMap(minMaxSpan.minSpan, percentExtent, viewExtend, true) : null, minMaxSpan.maxSpan != null ? linearMap(minMaxSpan.maxSpan, percentExtent, viewExtend, true) : null);
    var lastRange = this._range;
    var range = this._range = asc([linearMap(handleEnds[0], viewExtend, percentExtent, true), linearMap(handleEnds[1], viewExtend, percentExtent, true)]);
    return !lastRange || lastRange[0] !== range[0] || lastRange[1] !== range[1];
  };
  SliderZoomView.prototype._updateView = function (nonRealtime) {
    var displaybles = this._displayables;
    var handleEnds = this._handleEnds;
    var handleInterval = asc(handleEnds.slice());
    var size = this._size;
    each([0, 1], function (handleIndex) {
      // Handles
      var handle = displaybles.handles[handleIndex];
      var handleHeight = this._handleHeight;
      handle.attr({
        scaleX: handleHeight / 2,
        scaleY: handleHeight / 2,
        // This is a trick, by adding an extra tiny offset to let the default handle's end point align to the drag window.
        // NOTE: It may affect some custom shapes a bit. But we prefer to have better result by default.
        x: handleEnds[handleIndex] + (handleIndex ? -1 : 1),
        y: size[1] / 2 - handleHeight / 2
      });
    }, this);
    // Filler
    displaybles.filler.setShape({
      x: handleInterval[0],
      y: 0,
      width: handleInterval[1] - handleInterval[0],
      height: size[1]
    });
    var viewExtent = {
      x: handleInterval[0],
      width: handleInterval[1] - handleInterval[0]
    };
    // Move handle
    if (displaybles.moveHandle) {
      displaybles.moveHandle.setShape(viewExtent);
      displaybles.moveZone.setShape(viewExtent);
      // Force update path on the invisible object
      displaybles.moveZone.getBoundingRect();
      displaybles.moveHandleIcon && displaybles.moveHandleIcon.attr('x', viewExtent.x + viewExtent.width / 2);
    }
    // update clip path of shadow.
    var dataShadowSegs = displaybles.dataShadowSegs;
    var segIntervals = [0, handleInterval[0], handleInterval[1], size[0]];
    for (var i = 0; i < dataShadowSegs.length; i++) {
      var segGroup = dataShadowSegs[i];
      var clipPath = segGroup.getClipPath();
      if (!clipPath) {
        clipPath = new graphic.Rect();
        segGroup.setClipPath(clipPath);
      }
      clipPath.setShape({
        x: segIntervals[i],
        y: 0,
        width: segIntervals[i + 1] - segIntervals[i],
        height: size[1]
      });
    }
    this._updateDataInfo(nonRealtime);
  };
  SliderZoomView.prototype._updateDataInfo = function (nonRealtime) {
    var dataZoomModel = this.dataZoomModel;
    var displayables = this._displayables;
    var handleLabels = displayables.handleLabels;
    var orient = this._orient;
    var labelTexts = ['', ''];
    if (dataZoomModel.get('showDetail')) {
      var axisProxy = dataZoomModel.findRepresentativeAxisProxy();
      var scale = axisProxy.getAxisModel().axis.scale;
      if (axisProxy) {
        var range = this._range;
        var window_1;
        if (nonRealtime) {
          // See #4434, data and axis are not processed and reset yet in non-realtime mode.
          var calcWinInput = {
            start: range[0],
            end: range[1]
          };
          var alignTo = getAlignTo(dataZoomModel, axisProxy);
          if (alignTo) {
            var alignToWindow = alignTo.calculateDataWindow(calcWinInput).percentInverted;
            calcWinInput = {
              start: alignToWindow[0],
              end: alignToWindow[1]
            };
          }
          window_1 = axisProxy.calculateDataWindow(calcWinInput);
        } else {
          window_1 = axisProxy.getWindow();
        }
        labelTexts = [formatLabel(dataZoomModel, 0, window_1, scale), formatLabel(dataZoomModel, 1, window_1, scale)];
      }
    }
    var orderedHandleEnds = asc(this._handleEnds.slice());
    setLabel.call(this, 0);
    setLabel.call(this, 1);
    function setLabel(handleIndex) {
      // Label
      // Text should not transform by barGroup.
      // Ignore handlers transform
      var barTransform = graphic.getTransform(displayables.handles[handleIndex].parent, this.group);
      var direction = graphic.transformDirection(handleIndex === 0 ? 'right' : 'left', barTransform);
      var offset = this._handleWidth / 2 + LABEL_GAP;
      var textPoint = graphic.applyTransform([orderedHandleEnds[handleIndex] + (handleIndex === 0 ? -offset : offset), this._size[1] / 2], barTransform);
      handleLabels[handleIndex].setStyle({
        x: textPoint[0],
        y: textPoint[1],
        verticalAlign: orient === HORIZONTAL ? 'middle' : direction,
        align: orient === HORIZONTAL ? direction : 'center',
        text: labelTexts[handleIndex]
      });
    }
  };
  SliderZoomView.prototype._onOverDataInfoTriggerArea = function (isOver) {
    this._isOverDataInfoTriggerArea = isOver;
    this._showDataInfo(isOver);
  };
  /**
   * @param isEmphasis true: show, false: hide
   */
  SliderZoomView.prototype._showDataInfo = function (isEmphasis) {
    var handleLabel = this.dataZoomModel.get('handleLabel') || {};
    var normalShow = handleLabel.show || false;
    var emphasisHandleLabel = this.dataZoomModel.getModel(['emphasis', 'handleLabel']);
    var emphasisShow = emphasisHandleLabel.get('show') || false;
    // Dragging is considered as emphasis, unless emphasisShow is false
    var toShow = isEmphasis || this._dragging ? emphasisShow : normalShow;
    var displayables = this._displayables;
    var handleLabels = displayables.handleLabels;
    handleLabels[0].attr('invisible', !toShow);
    handleLabels[1].attr('invisible', !toShow);
    // Highlight move handle
    displayables.moveHandle && this.api[toShow ? 'enterEmphasis' : 'leaveEmphasis'](displayables.moveHandle, 1);
  };
  SliderZoomView.prototype._onActualMoveZoneDrift = function (dx, dy, event) {
    this.api.getZr().setCursorStyle('grabbing');
    this._onDragMove('all', dx, dy, event);
  };
  SliderZoomView.prototype._onActualMoveZoneDragStart = function (event) {
    event.target.attr('cursor', 'grabbing');
    this._showDataInfo(true);
  };
  SliderZoomView.prototype._onActualMoveZoneDragEnd = function (event) {
    event.target.attr('cursor', 'grab');
    this._onDragEnd();
  };
  SliderZoomView.prototype._onDragMove = function (handleIndex, dx, dy, event) {
    this._dragging = true;
    // For mobile device, prevent screen slider on the button.
    eventTool.stop(event.event);
    // Transform dx, dy to bar coordination.
    var barTransform = this._displayables.sliderGroup.getLocalTransform();
    var vertex = graphic.applyTransform([dx, dy], barTransform, true);
    var changed = this._updateInterval(handleIndex, vertex[0]);
    var realtime = this.dataZoomModel.get('realtime');
    this._updateView(!realtime);
    // Avoid dispatch dataZoom repeatly but range not changed,
    // which cause bad visual effect when progressive enabled.
    changed && realtime && this._dispatchZoomAction(true);
  };
  SliderZoomView.prototype._onDragEnd = function () {
    this._dragging = false;
    if (!this._isOverDataInfoTriggerArea) {
      // Drag end may occur on draggable bars, where data info should be still shown.
      this._showDataInfo(false);
    }
    // While in realtime mode and stream mode, dispatch action when
    // drag end will cause the whole view rerender, which is unnecessary.
    var realtime = this.dataZoomModel.get('realtime');
    !realtime && this._dispatchZoomAction(false);
  };
  SliderZoomView.prototype._onClickPanel = function (e) {
    var size = this._size;
    var localPoint = this._displayables.sliderGroup.transformCoordToLocal(e.offsetX, e.offsetY);
    if (localPoint[0] < 0 || localPoint[0] > size[0] || localPoint[1] < 0 || localPoint[1] > size[1]) {
      return;
    }
    var handleEnds = this._handleEnds;
    var center = (handleEnds[0] + handleEnds[1]) / 2;
    var changed = this._updateInterval('all', localPoint[0] - center);
    this._updateView();
    changed && this._dispatchZoomAction(false);
  };
  SliderZoomView.prototype._onBrushStart = function (e) {
    var x = e.offsetX;
    var y = e.offsetY;
    this._brushStart = new graphic.Point(x, y);
    this._brushing = true;
    this._brushStartTime = +new Date();
    // this._updateBrushRect(x, y);
  };
  SliderZoomView.prototype._onBrushEnd = function (e) {
    if (!this._brushing) {
      return;
    }
    var brushRect = this._displayables.brushRect;
    this._brushing = false;
    if (!brushRect) {
      return;
    }
    brushRect.attr('ignore', true);
    var brushShape = brushRect.shape;
    var brushEndTime = +new Date();
    // console.log(brushEndTime - this._brushStartTime);
    if (brushEndTime - this._brushStartTime < 200 && Math.abs(brushShape.width) < 5) {
      // Will treat it as a click
      return;
    }
    var viewExtend = this._getViewExtent();
    var percentExtent = [0, 100];
    var handleEnds = this._handleEnds = [brushShape.x, brushShape.x + brushShape.width];
    var minMaxSpan = this.dataZoomModel.findRepresentativeAxisProxy().getMinMaxSpan();
    // Restrict range.
    sliderMove(0, handleEnds, viewExtend, 0, minMaxSpan.minSpan != null ? linearMap(minMaxSpan.minSpan, percentExtent, viewExtend, true) : null, minMaxSpan.maxSpan != null ? linearMap(minMaxSpan.maxSpan, percentExtent, viewExtend, true) : null);
    this._range = asc([linearMap(handleEnds[0], viewExtend, percentExtent, true), linearMap(handleEnds[1], viewExtend, percentExtent, true)]);
    this._updateView();
    this._dispatchZoomAction(false);
  };
  SliderZoomView.prototype._onBrush = function (e) {
    if (this._brushing) {
      // For mobile device, prevent screen slider on the button.
      eventTool.stop(e.event);
      this._updateBrushRect(e.offsetX, e.offsetY);
    }
  };
  SliderZoomView.prototype._updateBrushRect = function (mouseX, mouseY) {
    var displayables = this._displayables;
    var dataZoomModel = this.dataZoomModel;
    var brushRect = displayables.brushRect;
    if (!brushRect) {
      brushRect = displayables.brushRect = new Rect({
        silent: true,
        style: dataZoomModel.getModel('brushStyle').getItemStyle()
      });
      displayables.sliderGroup.add(brushRect);
    }
    brushRect.attr('ignore', false);
    var brushStart = this._brushStart;
    var sliderGroup = this._displayables.sliderGroup;
    var endPoint = sliderGroup.transformCoordToLocal(mouseX, mouseY);
    var startPoint = sliderGroup.transformCoordToLocal(brushStart.x, brushStart.y);
    var size = this._size;
    endPoint[0] = Math.max(Math.min(size[0], endPoint[0]), 0);
    brushRect.setShape({
      x: startPoint[0],
      y: 0,
      width: endPoint[0] - startPoint[0],
      height: size[1]
    });
  };
  /**
   * This action will be throttled.
   */
  SliderZoomView.prototype._dispatchZoomAction = function (realtime) {
    var range = this._range;
    this.api.dispatchAction({
      type: 'dataZoom',
      from: this.uid,
      dataZoomId: this.dataZoomModel.id,
      animation: realtime ? REALTIME_ANIMATION_CONFIG : null,
      start: range[0],
      end: range[1]
    });
  };
  SliderZoomView.prototype._findCoordRect = function () {
    // Find the grid corresponding to the first axis referred by dataZoom.
    var rect;
    var coordSysInfoList = collectReferCoordSysModelInfo(this.dataZoomModel).infoList;
    if (!rect && coordSysInfoList.length) {
      var coordSys = coordSysInfoList[0].model.coordinateSystem;
      rect = coordSys.getRect && coordSys.getRect();
    }
    if (!rect) {
      var width = this.api.getWidth();
      var height = this.api.getHeight();
      rect = {
        x: width * 0.2,
        y: height * 0.2,
        width: width * 0.6,
        height: height * 0.6
      };
    }
    return rect;
  };
  SliderZoomView.type = 'dataZoom.slider';
  return SliderZoomView;
}(DataZoomView);
function formatLabel(dataZoomModel, extentIdx, window, scale) {
  var labelFormatter = dataZoomModel.get('labelFormatter');
  var labelPrecision = dataZoomModel.get('labelPrecision');
  if (labelPrecision == null || labelPrecision === 'auto') {
    labelPrecision = window.valuePrecision;
  }
  // Do not display values out of `SCALE_EXTENT_KIND_EFFECTIVE` - generally they are meaningless.
  // For example, `scaleExtent[0]` is often `0`, and negative values are unlikely to be meaningful.
  // That is, "nice" expansion and `SCALE_EXTENT_KIND_MAPPING` expansion are always not display in labels.
  var value = window.value[extentIdx];
  var valueStr = value == null || isNaN(value) ? '' : isOrdinalScale(scale) || isTimeScale(scale) ? scale.getLabel({
    value: Math.round(value)
  }) : isFinite(labelPrecision) ? round(value, labelPrecision, true) : value + '';
  return isFunction(labelFormatter) ? labelFormatter(value, valueStr) : isString(labelFormatter) ? labelFormatter.replace('{value}', valueStr) : valueStr;
}
function getOtherDim(thisDim) {
  // FIXME
  // 这个逻辑和getOtherAxis里一致，但是写在这里是否不好
  var map = {
    x: 'y',
    y: 'x',
    radius: 'angle',
    angle: 'radius'
  };
  return map[thisDim];
}
function getCursor(orient) {
  return orient === 'vertical' ? 'ns-resize' : 'ew-resize';
}
export default SliderZoomView;