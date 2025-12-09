import pandas as pd
import requests

def get_sci_data_logger_sn(glider_name,attached_time):
    # Example: Swagger URL endpoint
    url = 'https://prod.ceotr.ca/sensor_tracker/api/data_logger_on_platform/?platform_name={0}&attached_time={1}&depth=1'.format(
        glider_name, attached_time)
    # Make a GET request
    response = requests.get(url)
    # JSON response (if applicable)
    data = response.json()
    dl = []
    dl_id = []
    for item in data.get("results", []):
        data_logger = item.get("data_logger", {})
        serial = data_logger.get("serial")
        name = data_logger.get("name")
        data_logger_id = data_logger.get("id")

        platform  = item.get("platform",{})
        serial_platform = platform.get('serial_number')
        name_platform = platform.get('name')

        start_time = item.get('start_time',{})
        end_time = item.get('end_time',{})

        if 'Flight' not in name:
            print(f"Platform Serial Number: {serial_platform}, Name: {name_platform}")
            print(f"Data logger Serial Number: {serial}, Name: {name}")
            print(f"Data logger ID: {data_logger_id}")
            print('Start time: {0}'.format(start_time))
            print('End time: {0}'.format(end_time))
            dl.append(serial)
            dl_id.append(data_logger_id)
    return dl, dl_id
def get_instruments_on_datalogger(data_logger_id, attached_time):
    # Example: Swagger URL endpoint
    url = 'https://prod.ceotr.ca/sensor_tracker/api/instrument_on_data_logger/?data_logger_identifier=science%20computer&attached_time={0}&depth=1'.format(
        attached_time)
    # Make a GET request
    response = requests.get(url)
    # JSON response (if applicable)
    data = response.json()
    inst = []
    for item in data.get("results", []):
        data_logger = item.get("data_logger", {})
        dl_id = data_logger.get('id', {})
        instrument = item.get('instrument')
        if dl_id == data_logger_id:
            # print(data_logger)
            # print(instrument)
            # print(f"Instrument name: {instrument.get('short_name')}, Serial number: {instrument.get('serial')}")
            inst.append(f"Instrument name: {instrument.get('short_name')}, Serial number: {instrument.get('serial')}")
    return inst

def get_model_id_slocum_wave():
    #Get all the glider models
    url = 'https://prod.ceotr.ca/sensor_tracker/api/platform_type/'
    response = requests.get(url)
    data = response.json()

    slocum_model_id = []
    wave_model_id =[]
    for item in data.get("results", []):
        model = item.get("model", {})
        # print(model)
        if 'Slocum' in model:
            slocum_model_id.append(item.get("id",{}))
        elif 'Wave' in model:
            wave_model_id.append(item.get("id"))

    return slocum_model_id, wave_model_id

def get_all_dep_one_glider_type(glider_type, slocum_model_id, wave_model_id):
    #Get all the glider deployments
    url = 'https://prod.ceotr.ca/sensor_tracker/api/deployment/?model={0}&depth=1&limit=300'.format(glider_type)
    # Make a GET request
    response = requests.get(url)
    # JSON response (if applicable)
    data = response.json()
    dep_num = []
    for item in data.get("results", []):
        platform = item.get("platform", {})
        if (platform.get('platform_type', {}) in slocum_model_id) or (platform.get('platform_type', {}) in wave_model_id):
            # print('{0}, deployment number: {1}'.format(platform.get('name'),item.get('deployment_number')))
            dep_num.append(item.get('deployment_number'))
    return dep_num

if __name__ == "__main__":
    # This is an example that gets you all the instruments attached to a datalogger to a glider at a given time

    glider_name = 'SV3-1070 (C34164NS)'
    attached_time = '2025-08-24'
    data_logger_sn, data_logger_id = get_sci_data_logger_sn(glider_name, attached_time)
    inst = get_instruments_on_datalogger(data_logger_id[1], attached_time)
    print(inst)

    #Here is how you'd get all the slocum and wave glider deployment numbers
    slocum_model_id, wave_model_id = get_model_id_slocum_wave() #first find all the model numbers of slocum and wave gliders
    wave_glider_deployment_numbers = get_all_dep_one_glider_type('Wave', slocum_model_id, wave_model_id)
    slocum_glider_deployment_numbers = get_all_dep_one_glider_type('Slocum', slocum_model_id, wave_model_id)

    #find all the instruments on the following glider missions
    mission_pd = pd.DataFrame({
        'name1': ['cabot', 'sambro', 'cabot', 'scotia', 'scotia', 'peggy', 'cabot', 'cabot'],
        'date': ['2020-07-18', '2021-07-06', '2021-07-07', '2021-07-20', '2022-04-22', '2022-04-22', '2022-06-04', '2022-07-28']})
    for i in mission_pd.iloc:
        data_logger_sn, data_logger_id = get_sci_data_logger_sn(i.name1, i.date)
        inst = get_instruments_on_datalogger(data_logger_id[0], i.date)
        if 'opt' in ''.join(inst):
            print('Glider name: {0}, Date {1}'.format(i.name1, i.date))
            print(inst)
            print('Optode present!')
            print('')
            print('')