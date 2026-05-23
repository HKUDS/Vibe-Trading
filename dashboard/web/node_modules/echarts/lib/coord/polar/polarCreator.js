
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
import * as zrUtil from 'zrender/lib/core/util.js';
import Polar, { polarDimensions } from './Polar.js';
import { parsePercent } from '../../util/number.js';
import { createScaleByModel, determineAxisType, isAxisOnBand } from '../../coord/axisHelper.js';
import { COMPONENT_TYPE_POLAR, COORD_SYS_TYPE_POLAR } from './PolarModel.js';
import { SINGLE_REFERRING } from '../../util/model.js';
import { createBoxLayoutReference } from '../../util/layout.js';
import { scaleCalcNice } from '../axisNiceTicks.js';
import { AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE, scaleRawExtentInfoCreate } from '../scaleRawExtentInfo.js';
import { associateSeriesWithAxis } from '../axisStatistics.js';
/**
 * Resize method bound to the polar
 */
function resizePolar(polar, polarModel, api) {
  var center = polarModel.get('center');
  var refContainer = createBoxLayoutReference(polarModel, api).refContainer;
  polar.cx = parsePercent(center[0], refContainer.width) + refContainer.x;
  polar.cy = parsePercent(center[1], refContainer.height) + refContainer.y;
  var radiusAxis = polar.getRadiusAxis();
  var size = Math.min(refContainer.width, refContainer.height) / 2;
  var radius = polarModel.get('radius');
  if (radius == null) {
    radius = [0, '100%'];
  } else if (!zrUtil.isArray(radius)) {
    // r0 = 0
    radius = [0, radius];
  }
  var parsedRadius = [parsePercent(radius[0], size), parsePercent(radius[1], size)];
  radiusAxis.inverse ? radiusAxis.setExtent(parsedRadius[1], parsedRadius[0]) : radiusAxis.setExtent(parsedRadius[0], parsedRadius[1]);
}
/**
 * Update polar
 */
function updatePolarScale(ecModel, api) {
  var polar = this;
  var angleAxis = polar.getAngleAxis();
  var radiusAxis = polar.getRadiusAxis();
  scaleRawExtentInfoCreate(angleAxis, AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE);
  scaleRawExtentInfoCreate(radiusAxis, AXIS_EXTENT_INFO_BUILD_FROM_COORD_SYS_UPDATE);
  scaleCalcNice(angleAxis);
  scaleCalcNice(radiusAxis);
  // Fix extent of category angle axis
  if (angleAxis.type === 'category' && !angleAxis.onBand) {
    var extent = angleAxis.getExtent();
    var diff = 360 / angleAxis.scale.count();
    angleAxis.inverse ? extent[1] += diff : extent[1] -= diff;
    angleAxis.setExtent(extent[0], extent[1]);
  }
}
function isAngleAxisModel(axisModel) {
  return axisModel.mainType === 'angleAxis';
}
/**
 * Set common axis properties
 */
function setAxis(axis, axisModel) {
  var _a;
  axis.type = determineAxisType(axisModel);
  axis.scale = createScaleByModel(axisModel, axis.type, false);
  axis.onBand = isAxisOnBand(axis.scale, axisModel);
  axis.inverse = axisModel.get('inverse');
  if (isAngleAxisModel(axisModel)) {
    axis.inverse = axis.inverse !== axisModel.get('clockwise');
    var startAngle = axisModel.get('startAngle');
    var endAngle = (_a = axisModel.get('endAngle')) !== null && _a !== void 0 ? _a : startAngle + (axis.inverse ? -360 : 360);
    axis.setExtent(startAngle, endAngle);
  }
  // Inject axis instance
  axisModel.axis = axis;
  axis.model = axisModel;
}
var polarCreator = {
  dimensions: polarDimensions,
  create: function (ecModel, api) {
    var polarList = [];
    ecModel.eachComponent(COMPONENT_TYPE_POLAR, function (polarModel, idx) {
      var polar = new Polar(idx + '');
      // Inject resize and update method
      polar.update = updatePolarScale;
      var radiusAxis = polar.getRadiusAxis();
      var angleAxis = polar.getAngleAxis();
      var radiusAxisModel = polarModel.findAxisModel('radiusAxis');
      var angleAxisModel = polarModel.findAxisModel('angleAxis');
      setAxis(radiusAxis, radiusAxisModel);
      setAxis(angleAxis, angleAxisModel);
      resizePolar(polar, polarModel, api);
      polarList.push(polar);
      polarModel.coordinateSystem = polar;
      polar.model = polarModel;
    });
    // Inject coordinateSystem to series
    ecModel.eachSeries(function (seriesModel) {
      if (seriesModel.get('coordinateSystem') === COORD_SYS_TYPE_POLAR) {
        var polarModel = seriesModel.getReferringComponents(COMPONENT_TYPE_POLAR, SINGLE_REFERRING).models[0];
        if (process.env.NODE_ENV !== 'production') {
          if (!polarModel) {
            throw new Error('Polar "' + zrUtil.retrieve(seriesModel.get('polarIndex'), seriesModel.get('polarId'), 0) + '" not found');
          }
        }
        var polar = seriesModel.coordinateSystem = polarModel.coordinateSystem;
        if (polar) {
          associateSeriesWithAxis(polar.getRadiusAxis(), seriesModel, COORD_SYS_TYPE_POLAR);
          associateSeriesWithAxis(polar.getAngleAxis(), seriesModel, COORD_SYS_TYPE_POLAR);
        }
      }
    });
    return polarList;
  }
};
export default polarCreator;