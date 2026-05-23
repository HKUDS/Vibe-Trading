
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
import DataZoomModel from './DataZoomModel.js';
import { inheritDefaultOption } from '../../util/component.js';
import tokens from '../../visual/tokens.js';
var SliderZoomModel = /** @class */function (_super) {
  __extends(SliderZoomModel, _super);
  function SliderZoomModel() {
    var _this = _super !== null && _super.apply(this, arguments) || this;
    _this.type = SliderZoomModel.type;
    return _this;
  }
  SliderZoomModel.type = 'dataZoom.slider';
  SliderZoomModel.layoutMode = 'box';
  SliderZoomModel.defaultOption = inheritDefaultOption(DataZoomModel.defaultOption, {
    show: true,
    // deault value can only be drived in view stage.
    right: 'ph',
    top: 'ph',
    width: 'ph',
    height: 'ph',
    left: null,
    bottom: null,
    borderColor: tokens.color.accent10,
    borderRadius: 0,
    backgroundColor: tokens.color.transparent,
    // dataBackgroundColor: '#ddd',
    dataBackground: {
      lineStyle: {
        color: tokens.color.accent30,
        width: 0.5
      },
      areaStyle: {
        color: tokens.color.accent20,
        opacity: 0.2
      }
    },
    selectedDataBackground: {
      lineStyle: {
        color: tokens.color.accent40,
        width: 0.5
      },
      areaStyle: {
        color: tokens.color.accent20,
        opacity: 0.3
      }
    },
    // Color of selected window.
    fillerColor: 'rgba(135,175,274,0.2)',
    handleIcon: 'path://M-9.35,34.56V42m0-40V9.5m-2,0h4a2,2,0,0,1,2,2v21a2,2,0,0,1-2,2h-4a2,2,0,0,1-2-2v-21A2,2,0,0,1-11.35,9.5Z',
    // Percent of the slider height
    handleSize: '100%',
    handleStyle: {
      color: tokens.color.neutral00,
      borderColor: tokens.color.accent20
    },
    moveHandleSize: 7,
    moveHandleIcon: 'path://M-320.9-50L-320.9-50c18.1,0,27.1,9,27.1,27.1V85.7c0,18.1-9,27.1-27.1,27.1l0,0c-18.1,0-27.1-9-27.1-27.1V-22.9C-348-41-339-50-320.9-50z M-212.3-50L-212.3-50c18.1,0,27.1,9,27.1,27.1V85.7c0,18.1-9,27.1-27.1,27.1l0,0c-18.1,0-27.1-9-27.1-27.1V-22.9C-239.4-41-230.4-50-212.3-50z M-103.7-50L-103.7-50c18.1,0,27.1,9,27.1,27.1V85.7c0,18.1-9,27.1-27.1,27.1l0,0c-18.1,0-27.1-9-27.1-27.1V-22.9C-130.9-41-121.8-50-103.7-50z',
    moveHandleStyle: {
      color: tokens.color.accent40,
      opacity: 0.5
    },
    showDetail: true,
    showDataShadow: 'auto',
    realtime: true,
    zoomLock: false,
    textStyle: {
      color: tokens.color.tertiary
    },
    brushSelect: true,
    brushStyle: {
      color: tokens.color.accent30,
      opacity: 0.3
    },
    emphasis: {
      handleLabel: {
        show: true
      },
      handleStyle: {
        borderColor: tokens.color.accent40
      },
      moveHandleStyle: {
        opacity: 0.8
      }
    },
    defaultLocationEdgeGap: 15
  });
  return SliderZoomModel;
}(DataZoomModel);
export default SliderZoomModel;