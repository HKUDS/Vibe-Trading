
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
import BaseBarSeriesModel from './BaseBarSeries.js';
import createSeriesData from '../helper/createSeriesData.js';
import { inheritDefaultOption } from '../../util/component.js';
import tokens from '../../visual/tokens.js';
import { preparePipelineContext } from '../../util/model.js';
import { SERIES_TYPE_BAR } from '../../layout/barCommon.js';
var BarSeriesModel = /** @class */function (_super) {
  __extends(BarSeriesModel, _super);
  function BarSeriesModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = BarSeriesModel.type;
    return _this;
  }
  BarSeriesModel.prototype.getInitialData = function () {
    return createSeriesData(null, this, {
      useEncodeDefaulter: true,
      createInvertedIndices: !!this.get('realtimeSort', true) || null
    });
  };
  /**
   * @override
   */
  BarSeriesModel.prototype.getProgressive = function () {
    // Do not support progressive in normal mode.
    return this.get('large') ? this.get('progressive') : false;
  };
  /**
   * @implement
   */
  BarSeriesModel.prototype.__preparePipelineContext = function (view, pipeline) {
    var context = preparePipelineContext(this, view, pipeline);
    // Do not support progressive in normal mode.
    if (context.progressiveRender) {
      context.large = true;
    }
    return context;
  };
  BarSeriesModel.prototype.brushSelector = function (dataIndex, data, selectors) {
    return selectors.rect(data.getItemLayout(dataIndex));
  };
  BarSeriesModel.type = 'series.' + SERIES_TYPE_BAR;
  BarSeriesModel.dependencies = ['grid', 'polar'];
  BarSeriesModel.defaultOption = inheritDefaultOption(BaseBarSeriesModel.defaultOption, {
    // If clipped
    // Only available on cartesian2d
    clip: true,
    roundCap: false,
    showBackground: false,
    backgroundStyle: {
      color: 'rgba(180, 180, 180, 0.2)',
      borderColor: null,
      borderWidth: 0,
      borderType: 'solid',
      borderRadius: 0,
      shadowBlur: 0,
      shadowColor: null,
      shadowOffsetX: 0,
      shadowOffsetY: 0,
      opacity: 1
    },
    select: {
      itemStyle: {
        borderColor: tokens.color.primary,
        borderWidth: 2
      }
    },
    realtimeSort: false
  });
  return BarSeriesModel;
}(BaseBarSeriesModel);
export default BarSeriesModel;