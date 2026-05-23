
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
import { createBoxLayoutReference, getLayoutRect, applyPreserveAspect } from '../../util/layout.js';
import * as bbox from 'zrender/lib/core/bbox.js';
import { extend } from 'zrender/lib/core/util.js';
import { injectCoordSysByOption } from '../../core/CoordinateSystem.js';
import { createViewCoordSysSimply } from '../../component/helper/roamHelper.js';
function getViewRect(seriesModel, api, aspect) {
  var layoutRef = createBoxLayoutReference(seriesModel, api);
  var option = extend(seriesModel.getBoxLayoutParams(), {
    aspect: aspect
  });
  var viewRect = getLayoutRect(option, layoutRef.refContainer);
  return applyPreserveAspect(seriesModel, viewRect, aspect);
}
export default function createViewCoordSys(ecModel, api) {
  var viewList = [];
  ecModel.eachSeriesByType('graph', function (seriesModel) {
    injectCoordSysByOption({
      targetModel: seriesModel,
      coordSysType: 'view',
      coordSysProvider: createViewCoordSys,
      isDefaultDataCoordSys: true
    });
    function createViewCoordSys() {
      var data = seriesModel.getData();
      var positions = data.mapArray(function (idx) {
        var itemModel = data.getItemModel(idx);
        return [+itemModel.get('x'), +itemModel.get('y')];
      });
      var min = [];
      var max = [];
      bbox.fromPoints(positions, min, max);
      // If width or height is 0
      if (max[0] - min[0] === 0) {
        max[0] += 1;
        min[0] -= 1;
      }
      if (max[1] - min[1] === 0) {
        max[1] += 1;
        min[1] -= 1;
      }
      var aspect = (max[0] - min[0]) / (max[1] - min[1]);
      // FIXME If get view rect after data processed?
      var viewRect = getViewRect(seriesModel, api, aspect);
      // Position may be NaN (e.g., in force layout), use view rect instead
      if (isNaN(aspect)) {
        min = [viewRect.x, viewRect.y];
        max = [viewRect.x + viewRect.width, viewRect.y + viewRect.height];
      }
      var bbWidth = max[0] - min[0];
      var bbHeight = max[1] - min[1];
      var viewCoordSys = createViewCoordSysSimply(seriesModel, api, min[0], min[1], bbWidth, bbHeight, viewRect);
      viewList.push(viewCoordSys);
      return viewCoordSys;
    }
  });
  return viewList;
}