
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
import IndicatorAxis from './IndicatorAxis.js';
import IntervalScale from '../../scale/Interval.js';
import * as numberUtil from '../../util/number.js';
import { COMPONENT_TYPE_RADAR, COORD_SYS_TYPE_RADAR, RADAR_DEFAULT_SPLIT_NUMBER, SERIES_TYPE_RADAR } from './RadarModel.js';
import { map, each, isString, isNumber } from 'zrender/lib/core/util.js';
import { scaleCalcAlign } from '../axisAlignTicks.js';
import { createBoxLayoutReference } from '../../util/layout.js';
import { AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE, scaleRawExtentInfoCreate } from '../scaleRawExtentInfo.js';
import { ensureValidSplitNumber } from '../../scale/helper.js';
import { associateSeriesWithAxis } from '../axisStatistics.js';
var Radar = /** @class */function () {
  function Radar(radarModel, ecModel, api) {
    this.type = COORD_SYS_TYPE_RADAR;
    /**
     *
     * Radar dimensions
     */
    this.dimensions = [];
    this._model = radarModel;
    this._indicatorAxes = map(radarModel.getIndicatorModels(), function (indicatorModel, idx) {
      var dim = 'indicator_' + idx;
      var indicatorAxis = new IndicatorAxis(dim, new IntervalScale()
      // (indicatorModel.get('axisType') === 'log') ? new LogScale() : new IntervalScale()
      );
      indicatorAxis.name = indicatorModel.get('name');
      // Inject model and axis
      indicatorAxis.model = indicatorModel;
      indicatorModel.axis = indicatorAxis;
      this.dimensions.push(dim);
      return indicatorAxis;
    }, this);
    this.resize(radarModel, api);
  }
  Radar.prototype.getIndicatorAxes = function () {
    return this._indicatorAxes;
  };
  Radar.prototype.dataToPoint = function (value, indicatorIndex) {
    var indicatorAxis = this._indicatorAxes[indicatorIndex];
    return this.coordToPoint(indicatorAxis.dataToCoord(value), indicatorIndex);
  };
  // TODO: API should be coordToPoint([coord, indicatorIndex])
  Radar.prototype.coordToPoint = function (coord, indicatorIndex) {
    var indicatorAxis = this._indicatorAxes[indicatorIndex];
    var angle = indicatorAxis.angle;
    var x = this.cx + coord * Math.cos(angle);
    var y = this.cy - coord * Math.sin(angle);
    return [x, y];
  };
  Radar.prototype.pointToData = function (pt) {
    var dx = pt[0] - this.cx;
    var dy = pt[1] - this.cy;
    var radius = Math.sqrt(dx * dx + dy * dy);
    dx /= radius;
    dy /= radius;
    var radian = Math.atan2(-dy, dx);
    // Find the closest angle
    // FIXME index can calculated directly
    var minRadianDiff = Infinity;
    var closestAxis;
    var closestAxisIdx = -1;
    for (var i = 0; i < this._indicatorAxes.length; i++) {
      var indicatorAxis = this._indicatorAxes[i];
      var diff = Math.abs(radian - indicatorAxis.angle);
      if (diff < minRadianDiff) {
        closestAxis = indicatorAxis;
        closestAxisIdx = i;
        minRadianDiff = diff;
      }
    }
    return [closestAxisIdx, +(closestAxis && closestAxis.coordToData(radius))];
  };
  Radar.prototype.resize = function (radarModel, api) {
    var refContainer = createBoxLayoutReference(radarModel, api).refContainer;
    var center = radarModel.get('center');
    var clockwise = radarModel.get('clockwise') || false;
    var viewSize = Math.min(refContainer.width, refContainer.height) / 2;
    this.cx = numberUtil.parsePercent(center[0], refContainer.width) + refContainer.x;
    this.cy = numberUtil.parsePercent(center[1], refContainer.height) + refContainer.y;
    this.startAngle = radarModel.get('startAngle') * Math.PI / 180;
    // radius may be single value like `20`, `'80%'`, or array like `[10, '80%']`
    var radius = radarModel.get('radius');
    if (isString(radius) || isNumber(radius)) {
      radius = [0, radius];
    }
    this.r0 = numberUtil.parsePercent(radius[0], viewSize);
    this.r = numberUtil.parsePercent(radius[1], viewSize);
    var sign = clockwise ? -1 : 1;
    each(this._indicatorAxes, function (indicatorAxis, idx) {
      indicatorAxis.setExtent(this.r0, this.r);
      var angle = this.startAngle + sign * idx * Math.PI * 2 / this._indicatorAxes.length;
      // Normalize to [-PI, PI]
      angle = Math.atan2(Math.sin(angle), Math.cos(angle));
      indicatorAxis.angle = angle;
    }, this);
  };
  Radar.prototype.update = function (ecModel, api) {
    var indicatorAxes = this._indicatorAxes;
    var radarModel = this._model;
    var splitNumber = ensureValidSplitNumber(radarModel.get('splitNumber'), RADAR_DEFAULT_SPLIT_NUMBER);
    var dummyScale = new IntervalScale();
    dummyScale.setExtent(0, splitNumber);
    dummyScale.setConfig({
      interval: 1
    });
    // Force all the axis fixing the maxSplitNumber.
    each(indicatorAxes, function (indicatorAxis) {
      scaleRawExtentInfoCreate(indicatorAxis, AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE);
      scaleCalcAlign(indicatorAxis, dummyScale);
    });
  };
  Radar.prototype.convertToPixel = function (ecModel, finder, value) {
    console.warn('Not implemented.');
    return null;
  };
  Radar.prototype.convertFromPixel = function (ecModel, finder, pixel) {
    console.warn('Not implemented.');
    return null;
  };
  Radar.prototype.containPoint = function (point) {
    console.warn('Not implemented.');
    return false;
  };
  Radar.create = function (ecModel, api) {
    var radarList = [];
    ecModel.eachComponent(COMPONENT_TYPE_RADAR, function (radarModel) {
      var radar = new Radar(radarModel, ecModel, api);
      radarList.push(radar);
      radarModel.coordinateSystem = radar;
    });
    ecModel.eachSeriesByType(SERIES_TYPE_RADAR, function (radarSeries) {
      if (radarSeries.get('coordinateSystem') === COORD_SYS_TYPE_RADAR) {
        // Inject coordinate system
        // @ts-ignore
        var radar = radarSeries.coordinateSystem = radarList[radarSeries.get('radarIndex') || 0];
        if (radar) {
          each(radar.getIndicatorAxes(), function (indicatorAxis) {
            associateSeriesWithAxis(indicatorAxis, radarSeries, COORD_SYS_TYPE_RADAR);
          });
        }
      }
    });
    return radarList;
  };
  /**
   * Radar dimensions is based on the data
   */
  Radar.dimensions = [];
  return Radar;
}();
export default Radar;