
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
import GeoModel from '../../coord/geo/GeoModel.js';
import geoCreator from '../../coord/geo/geoCreator.js';
import { COMPONENT_MAIN_TYPE_SERIES } from '../../util/types.js';
import { each } from 'zrender/lib/core/util.js';
import { mapSeriesNeedsDrawMap } from '../../chart/map/MapSeries.js';
import GeoView from './GeoView.js';
import geoSourceManager from '../../coord/geo/geoSourceManager.js';
import { makeQueryConditionKindA } from '../../util/model.js';
import { ownRoamModelCoordSysUpdateInAction, ownRoamViewUpdateDirectlyInAction } from '../../coord/View.js';
function registerMap(mapName, geoJson, specialAreas) {
  geoSourceManager.registerMap(mapName, geoJson, specialAreas);
}
export function install(registers) {
  registers.registerCoordinateSystem('geo', geoCreator);
  registers.registerComponentModel(GeoModel);
  registers.registerComponentView(GeoView);
  registers.registerImpl('registerMap', registerMap);
  registers.registerImpl('getMap', function (mapName) {
    return geoSourceManager.getMapForUser(mapName);
  });
  function makeAction(method, actionInfo) {
    actionInfo.update = 'geo:updateSelectStatus';
    registers.registerAction(actionInfo, function (payload, ecModel) {
      var selected = {};
      var allSelected = [];
      ecModel.eachComponent({
        mainType: 'geo',
        query: payload
      }, function (geoModel) {
        geoModel[method](payload.name);
        var geo = geoModel.coordinateSystem;
        each(geo.regions, function (region) {
          selected[region.name] = geoModel.isSelected(region.name) || false;
        });
        // Notice: there might be duplicated name in different regions.
        var names = [];
        each(selected, function (v, name) {
          selected[name] && names.push(name);
        });
        allSelected.push({
          geoIndex: geoModel.componentIndex,
          // Use singular, the same naming convention as the event `selectchanged`.
          name: names
        });
      });
      return {
        selected: selected,
        allSelected: allSelected,
        name: payload.name
      };
    });
  }
  makeAction('toggleSelected', {
    type: 'geoToggleSelect',
    event: 'geoselectchanged'
  });
  makeAction('select', {
    type: 'geoSelect',
    event: 'geoselected'
  });
  makeAction('unSelect', {
    type: 'geoUnSelect',
    event: 'geounselected'
  });
  /**
   * @payload
   * @property {string} [componentType=series]
   * @property {number} [dx]
   * @property {number} [dy]
   * @property {number} [zoom]
   * @property {number} [originX]
   * @property {number} [originY]
   */
  registers.registerAction({
    type: 'geoRoam',
    event: 'geoRoam',
    update: 'updateTransform'
  }, function (payload, ecModel, api) {
    // `payload.componentType` is supported only for backward compatibility.
    var mainType = payload.componentType || (payload.geoId != null || payload.geoName != null || payload.geoIndex != null ? 'geo' : COMPONENT_MAIN_TYPE_SERIES);
    var isSeries = mainType === COMPONENT_MAIN_TYPE_SERIES;
    if (mainType !== 'geo' && !isSeries) {
      return;
    }
    var subType = isSeries ? 'map' : null;
    ecModel.eachComponent(makeQueryConditionKindA(payload, mainType, subType), function (componentOrSeries) {
      if (isSeries
      // Only when `needsDrawMap: true`, the `MapSeries` host geo coord sys and call `MapDraw`.
      && !mapSeriesNeedsDrawMap(componentOrSeries)) {
        return;
      }
      // Since 'updateTransform' is used, geo model and view update firstly here, and then series
      // and components laid out on this VIEW_COORD_SYS update in `View['updateTransform']`.
      ownRoamModelCoordSysUpdateInAction(payload, componentOrSeries, isSeries ? componentOrSeries.seriesGroup.r : null);
      ownRoamViewUpdateDirectlyInAction(payload, componentOrSeries, ecModel, api);
    });
  });
}