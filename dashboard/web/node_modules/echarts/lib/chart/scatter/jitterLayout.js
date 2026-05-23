
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
import { needFixJitter, fixJitter } from '../../util/jitter.js';
import createRenderPlanner from '../helper/createRenderPlanner.js';
import { COORD_SYS_TYPE_CARTESIAN_2D } from '../../coord/cartesian/GridModel.js';
import { COORD_SYS_TYPE_SINGLE } from '../../coord/single/AxisModel.js';
import { validateUpstreamOutputRange } from '../../util/model.js';
export default function jitterLayout() {
  return {
    seriesType: 'scatter',
    plan: createRenderPlanner(),
    reset: function (seriesModel) {
      var coordSys = seriesModel.coordinateSystem;
      if (!coordSys || coordSys.type !== COORD_SYS_TYPE_CARTESIAN_2D && coordSys.type !== COORD_SYS_TYPE_SINGLE) {
        return;
      }
      var baseAxis = coordSys.getBaseAxis && coordSys.getBaseAxis();
      var hasJitter = baseAxis && needFixJitter(seriesModel, baseAxis);
      if (!hasJitter) {
        return;
      }
      var dim = baseAxis.dim;
      var orient = baseAxis.orient;
      var isSingleY = orient === 'horizontal' && baseAxis.type !== 'category' || orient === 'vertical' && baseAxis.type === 'category';
      var jitterOnY = dim === 'y' || dim === 'single' && isSingleY;
      var jitterOnX = dim === 'x' || dim === 'single' && !isSingleY;
      if (!jitterOnY && !jitterOnX) {
        return;
      }
      return {
        progress: function (params, data) {
          var points = data.getLayout('points');
          var hasPoints = !!points;
          if (process.env.NODE_ENV !== 'production') {
            hasPoints && validateUpstreamOutputRange(data.getLayout('pointsRange'), params);
          }
          for (var i = params.start; i < params.end; i++) {
            var offset = hasPoints ? (i - params.start) * 2 : -1;
            var layout = hasPoints ? [points[offset], points[offset + 1]] : data.getItemLayout(i);
            if (!layout) {
              continue;
            }
            var rawSize = data.getItemVisual(i, 'symbolSize');
            var size = rawSize instanceof Array ? (rawSize[1] + rawSize[0]) / 2 : rawSize;
            if (jitterOnY) {
              // x is fixed, and y is floating
              var jittered = fixJitter(baseAxis, layout[0], layout[1], size / 2);
              if (hasPoints) {
                points[offset + 1] = jittered;
              } else {
                layout[1] = jittered;
              }
            } else if (jitterOnX) {
              // y is fixed, and x is floating
              var jittered = fixJitter(baseAxis, layout[1], layout[0], size / 2);
              if (hasPoints) {
                points[offset] = jittered;
              } else {
                layout[0] = jittered;
              }
            }
          }
        }
      };
    }
  };
}