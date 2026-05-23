
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
/**
 * Single coordinates system.
 */
import SingleAxis from './SingleAxis.js';
import * as axisHelper from '../axisHelper.js';
import { createBoxLayoutReference, getLayoutRect } from '../../util/layout.js';
import { COORD_SYS_TYPE_SINGLE } from './AxisModel.js';
import { scaleCalcNice } from '../axisNiceTicks.js';
import { AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE, scaleRawExtentInfoCreate } from '../scaleRawExtentInfo.js';
export var singleDimensions = ['single'];
/**
 * Create a single coordinates system.
 */
var Single = /** @class */function () {
  function Single(axisModel, ecModel, api) {
    this.type = COORD_SYS_TYPE_SINGLE;
    this.dimension = 'single';
    /**
     * Add it just for draw tooltip.
     */
    this.dimensions = singleDimensions;
    this.axisPointerEnabled = true;
    this.model = axisModel;
    this._init(axisModel, ecModel, api);
  }
  /**
   * Initialize single coordinate system.
   */
  Single.prototype._init = function (axisModel, ecModel, api) {
    var dim = this.dimension;
    var axisType = axisHelper.determineAxisType(axisModel);
    var axis = new SingleAxis(dim, axisHelper.createScaleByModel(axisModel, axisType, true), [0, 0], axisType, axisModel.get('position'));
    axis.onBand = axisHelper.isAxisOnBand(axis.scale, axisModel);
    axis.inverse = axisModel.get('inverse');
    axis.orient = axisModel.get('orient');
    axisModel.axis = axis;
    axis.model = axisModel;
    axis.coordinateSystem = this;
    this._axis = axis;
  };
  /**
   * Update axis scale after data processed
   */
  Single.prototype.update = function (ecModel, api) {
    var axis = this._axis;
    scaleRawExtentInfoCreate(axis, AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE);
    scaleCalcNice(axis);
  };
  /**
   * Resize the single coordinate system.
   */
  Single.prototype.resize = function (axisModel, api) {
    var refContainer = createBoxLayoutReference(axisModel, api).refContainer;
    this._rect = getLayoutRect(axisModel.getBoxLayoutParams(), refContainer);
    this._adjustAxis();
  };
  Single.prototype.getRect = function () {
    return this._rect;
  };
  Single.prototype._adjustAxis = function () {
    var rect = this._rect;
    var axis = this._axis;
    var isHorizontal = axis.isHorizontal();
    var extent = isHorizontal ? [0, rect.width] : [0, rect.height];
    var idx = axis.inverse ? 1 : 0;
    axis.setExtent(extent[idx], extent[1 - idx]);
    this._updateAxisTransform(axis, isHorizontal ? rect.x : rect.y);
  };
  Single.prototype._updateAxisTransform = function (axis, coordBase) {
    var axisExtent = axis.getExtent();
    var extentSum = axisExtent[0] + axisExtent[1];
    var isHorizontal = axis.isHorizontal();
    axis.toGlobalCoord = isHorizontal ? function (coord) {
      return coord + coordBase;
    } : function (coord) {
      return extentSum - coord + coordBase;
    };
    axis.toLocalCoord = isHorizontal ? function (coord) {
      return coord - coordBase;
    } : function (coord) {
      return extentSum - coord + coordBase;
    };
  };
  /**
   * Get axis.
   */
  Single.prototype.getAxis = function () {
    return this._axis;
  };
  /**
   * Get axis, add it just for draw tooltip.
   */
  Single.prototype.getBaseAxis = function () {
    return this._axis;
  };
  Single.prototype.getAxes = function () {
    return [this._axis];
  };
  Single.prototype.getTooltipAxes = function () {
    return {
      baseAxes: [this.getAxis()],
      // Empty otherAxes
      otherAxes: []
    };
  };
  /**
   * If contain point.
   */
  Single.prototype.containPoint = function (point) {
    var rect = this.getRect();
    var axis = this.getAxis();
    var orient = axis.orient;
    if (orient === 'horizontal') {
      return axis.contain(axis.toLocalCoord(point[0])) && point[1] >= rect.y && point[1] <= rect.y + rect.height;
    } else {
      return axis.contain(axis.toLocalCoord(point[1])) && point[0] >= rect.y && point[0] <= rect.y + rect.height;
    }
  };
  Single.prototype.pointToData = function (point, reserved, out) {
    out = out || [];
    var axis = this.getAxis();
    out[0] = axis.coordToData(axis.toLocalCoord(point[axis.orient === 'horizontal' ? 0 : 1]));
    return out;
  };
  /**
   * Convert the series data to concrete point.
   * Can be [val] | val
   */
  Single.prototype.dataToPoint = function (val, reserved, out) {
    var axis = this.getAxis();
    var rect = this.getRect();
    out = out || [];
    var idx = axis.orient === 'horizontal' ? 0 : 1;
    if (val instanceof Array) {
      val = val[0];
    }
    out[idx] = axis.toGlobalCoord(axis.dataToCoord(+val));
    out[1 - idx] = idx === 0 ? rect.y + rect.height / 2 : rect.x + rect.width / 2;
    return out;
  };
  Single.prototype.convertToPixel = function (ecModel, finder, value) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? this.dataToPoint(value) : null;
  };
  Single.prototype.convertFromPixel = function (ecModel, finder, pixel) {
    var coordSys = getCoordSys(finder);
    return coordSys === this ? this.pointToData(pixel) : null;
  };
  return Single;
}();
function getCoordSys(finder) {
  var seriesModel = finder.seriesModel;
  var singleModel = finder.singleAxisModel;
  return singleModel && singleModel.coordinateSystem || seriesModel && seriesModel.coordinateSystem;
}
export default Single;