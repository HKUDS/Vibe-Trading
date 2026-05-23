
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
import ComponentModel from '../../model/Component.js';
import { error } from '../../util/log.js';
import tokens from '../../visual/tokens.js';
import { injectThumbnailBridge } from '../helper/thumbnailBridge.js';
import { ThumbnailBridgeImpl } from './ThumbnailBridgeImpl.js';
var ThumbnailModel = /** @class */function (_super) {
  __extends(ThumbnailModel, _super);
  function ThumbnailModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = ThumbnailModel.type;
    _this.preventAutoZ = true;
    return _this;
  }
  ThumbnailModel.prototype.optionUpdated = function (newCptOption, isInit) {
    this._updateBridge();
  };
  ThumbnailModel.prototype._updateBridge = function () {
    var bridge = this._birdge = this._birdge || new ThumbnailBridgeImpl(this);
    // Clear all, in case of option changed.
    this._target = null;
    this.ecModel.eachSeries(function (series) {
      injectThumbnailBridge(series, null);
    });
    if (this.shouldShow()) {
      var target = this.getTarget();
      // If a component is targeted by more than one thumbnails, simply only the last one works.
      injectThumbnailBridge(target.baseMapProvider, bridge);
    }
  };
  ThumbnailModel.prototype.shouldShow = function () {
    return this.getShallow('show', true);
  };
  ThumbnailModel.prototype.getBridge = function () {
    return this._birdge;
  };
  ThumbnailModel.prototype.getTarget = function () {
    if (this._target) {
      return this._target;
    }
    // Find by `seriesId`/`seriesIndex`.
    var series = this.getReferringComponents('series', {
      useDefault: false,
      enableAll: false,
      enableNone: false
    }).models[0];
    if (series) {
      if (series.subType !== 'graph') {
        series = null;
        if (process.env.NODE_ENV !== 'production') {
          error("series." + series.subType + " is not supported in thumbnail.", true);
        }
      }
    } else {
      // If no xxxId and xxxIndex specified, find the first series.graph. If other components,
      // such as geo, is supported in future, the default stretagy may be extended.
      series = this.ecModel.queryComponents({
        mainType: 'series',
        subType: 'graph'
      })[0];
    }
    this._target = {
      baseMapProvider: series
    };
    return this._target;
  };
  ThumbnailModel.type = 'thumbnail';
  ThumbnailModel.layoutMode = 'box';
  // All the supported components should be added here.
  ThumbnailModel.dependencies = ['series', 'geo'];
  ThumbnailModel.defaultOption = {
    show: true,
    right: 1,
    bottom: 1,
    height: '25%',
    width: '25%',
    itemStyle: {
      // Use echarts option.backgorundColor by default.
      borderColor: tokens.color.border,
      borderWidth: 2
    },
    windowStyle: {
      borderWidth: 1,
      color: tokens.color.neutral30,
      borderColor: tokens.color.neutral40,
      opacity: 0.3
    },
    z: 10
  };
  return ThumbnailModel;
}(ComponentModel);
export { ThumbnailModel };