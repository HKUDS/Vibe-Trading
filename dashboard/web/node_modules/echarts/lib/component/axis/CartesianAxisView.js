
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
import * as zrUtil from 'zrender/lib/core/util.js';
import * as graphic from '../../util/graphic.js';
import AxisView from './AxisView.js';
import { rectCoordAxisBuildSplitArea, rectCoordAxisHandleRemove } from './axisSplitHelper.js';
import { getAxisBreakHelper } from './axisBreakHelper.js';
import { shouldAxisShow } from '../../coord/axisHelper.js';
var selfBuilderAttrs = ['splitArea', 'splitLine', 'minorSplitLine', 'breakArea'];
var CartesianAxisView = /** @class */function (_super) {
  __extends(CartesianAxisView, _super);
  function CartesianAxisView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = CartesianAxisView.type;
    _this.axisPointerClass = 'CartesianAxisPointer';
    return _this;
  }
  /**
   * @override
   */
  CartesianAxisView.prototype.render = function (axisModel, ecModel, api, payload) {
    this.group.removeAll();
    var oldAxisGroup = this._axisGroup;
    this._axisGroup = new graphic.Group();
    this.group.add(this._axisGroup);
    if (!shouldAxisShow(axisModel)) {
      return;
    }
    this._axisGroup.add(axisModel.axis.axisBuilder.group);
    zrUtil.each(selfBuilderAttrs, function (name) {
      if (axisModel.get([name, 'show'])) {
        axisElementBuilders[name](this, this._axisGroup, axisModel, axisModel.getCoordSysModel(), api);
      }
    }, this);
    // THIS is a special case for bar racing chart.
    // Update the axis label from the natural initial layout to
    // sorted layout should has no animation.
    var isInitialSortFromBarRacing = payload && payload.type === 'changeAxisOrder' && payload.isInitSort;
    if (!isInitialSortFromBarRacing) {
      graphic.groupTransition(oldAxisGroup, this._axisGroup, axisModel);
    }
    _super.prototype.render.call(this, axisModel, ecModel, api, payload);
  };
  CartesianAxisView.prototype.remove = function () {
    rectCoordAxisHandleRemove(this);
  };
  CartesianAxisView.type = 'cartesianAxis';
  return CartesianAxisView;
}(AxisView);
var axisElementBuilders = {
  splitLine: function (axisView, axisGroup, axisModel, gridModel, api) {
    var axis = axisModel.axis;
    if (axis.scale.isBlank()) {
      return;
    }
    var splitLineModel = axisModel.getModel('splitLine');
    var lineStyleModel = splitLineModel.getModel('lineStyle');
    var lineColors = lineStyleModel.get('color');
    var showMinLine = splitLineModel.get('showMinLine') !== false;
    var showMaxLine = splitLineModel.get('showMaxLine') !== false;
    lineColors = zrUtil.isArray(lineColors) ? lineColors : [lineColors];
    var gridRect = gridModel.coordinateSystem.getRect();
    var isHorizontal = axis.isHorizontal();
    var lineCount = 0;
    var ticksCoords = axis.getTicksCoords({
      tickModel: splitLineModel,
      breakTicks: 'none',
      pruneByBreak: 'preserve_extent_bound'
    });
    var p1 = [];
    var p2 = [];
    var lineStyle = lineStyleModel.getLineStyle();
    for (var i = 0; i < ticksCoords.length; i++) {
      var tickCoord = axis.toGlobalCoord(ticksCoords[i].coord);
      if (i === 0 && !showMinLine || i === ticksCoords.length - 1 && !showMaxLine) {
        continue;
      }
      var tickValue = ticksCoords[i].tickValue;
      if (isHorizontal) {
        p1[0] = tickCoord;
        p1[1] = gridRect.y;
        p2[0] = tickCoord;
        p2[1] = gridRect.y + gridRect.height;
      } else {
        p1[0] = gridRect.x;
        p1[1] = tickCoord;
        p2[0] = gridRect.x + gridRect.width;
        p2[1] = tickCoord;
      }
      var colorIndex = lineCount++ % lineColors.length;
      var line = new graphic.Line({
        anid: tickValue != null ? 'line_' + tickValue : null,
        autoBatch: true,
        shape: {
          x1: p1[0],
          y1: p1[1],
          x2: p2[0],
          y2: p2[1]
        },
        style: zrUtil.defaults({
          stroke: lineColors[colorIndex]
        }, lineStyle),
        silent: true
      });
      graphic.subPixelOptimizeLine(line.shape, lineStyle.lineWidth);
      axisGroup.add(line);
    }
  },
  minorSplitLine: function (axisView, axisGroup, axisModel, gridModel, api) {
    var axis = axisModel.axis;
    var minorSplitLineModel = axisModel.getModel('minorSplitLine');
    var lineStyleModel = minorSplitLineModel.getModel('lineStyle');
    var gridRect = gridModel.coordinateSystem.getRect();
    var isHorizontal = axis.isHorizontal();
    var minorTicksCoords = axis.getMinorTicksCoords();
    if (!minorTicksCoords.length) {
      return;
    }
    var p1 = [];
    var p2 = [];
    var lineStyle = lineStyleModel.getLineStyle();
    for (var i = 0; i < minorTicksCoords.length; i++) {
      for (var k = 0; k < minorTicksCoords[i].length; k++) {
        var tickCoord = axis.toGlobalCoord(minorTicksCoords[i][k].coord);
        if (isHorizontal) {
          p1[0] = tickCoord;
          p1[1] = gridRect.y;
          p2[0] = tickCoord;
          p2[1] = gridRect.y + gridRect.height;
        } else {
          p1[0] = gridRect.x;
          p1[1] = tickCoord;
          p2[0] = gridRect.x + gridRect.width;
          p2[1] = tickCoord;
        }
        var line = new graphic.Line({
          anid: 'minor_line_' + minorTicksCoords[i][k].tickValue,
          autoBatch: true,
          shape: {
            x1: p1[0],
            y1: p1[1],
            x2: p2[0],
            y2: p2[1]
          },
          style: lineStyle,
          silent: true
        });
        graphic.subPixelOptimizeLine(line.shape, lineStyle.lineWidth);
        axisGroup.add(line);
      }
    }
  },
  splitArea: function (axisView, axisGroup, axisModel, gridModel, api) {
    rectCoordAxisBuildSplitArea(axisView, axisGroup, axisModel, gridModel);
  },
  breakArea: function (axisView, axisGroup, axisModel, gridModel, api) {
    var axisBreakHelper = getAxisBreakHelper();
    var scale = axisModel.axis.scale;
    if (axisBreakHelper && scale.type !== 'ordinal') {
      axisBreakHelper.rectCoordBuildBreakAxis(axisGroup, axisView, axisModel, gridModel.coordinateSystem.getRect(), api);
    }
  }
};
var CartesianXAxisView = /** @class */function (_super) {
  __extends(CartesianXAxisView, _super);
  function CartesianXAxisView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = CartesianXAxisView.type;
    return _this;
  }
  CartesianXAxisView.type = 'xAxis';
  return CartesianXAxisView;
}(CartesianAxisView);
export { CartesianXAxisView };
var CartesianYAxisView = /** @class */function (_super) {
  __extends(CartesianYAxisView, _super);
  function CartesianYAxisView() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = CartesianXAxisView.type;
    return _this;
  }
  CartesianYAxisView.type = 'yAxis';
  return CartesianYAxisView;
}(CartesianAxisView);
export { CartesianYAxisView };
export default CartesianAxisView;