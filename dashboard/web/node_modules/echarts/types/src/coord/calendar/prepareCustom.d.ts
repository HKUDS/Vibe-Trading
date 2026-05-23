import type Calendar from './Calendar.js';
export default function calendarPrepareCustom(coordSys: Calendar): {
    coordSys: {
        type: string;
        x: number;
        y: number;
        width: number;
        height: number;
        cellWidth: number;
        cellHeight: number;
        rangeInfo: {
            start: import("./Calendar").CalendarParsedDateInfo;
            end: import("./Calendar").CalendarParsedDateInfo;
            weeks: number;
            dayCount: number;
        };
    };
    api: {
        coord: (data: Parameters<Calendar['dataToPoint']>[0], clamp?: Parameters<Calendar['dataToPoint']>[1]) => ReturnType<Calendar['dataToPoint']>;
        layout: (data: Parameters<Calendar['dataToLayout']>[0], clamp?: Parameters<Calendar['dataToLayout']>[1]) => ReturnType<Calendar['dataToLayout']>;
    };
};
