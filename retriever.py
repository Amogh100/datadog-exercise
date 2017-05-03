from collections import Counter
from datetime import datetime

class Retriever():
    """Class whose goal is to get a website's monitoring data and compute interesting metrics about it.
    It also has a method to track and warn about availability alerts.

    Attributes:
        URL (str): URL of the monitored website.
        influxClient (InfluxDBClient): Client for the InfluxDB used to store monitoring data.
        alertData (dict): Data about the current alert (if there is an alert going on).
            alertStatus (bool): Indicates if there is an alert going on.
            alertNumber (int): Number of the alert (used to reference alerts).
            alertTime (datetime.datetime): Start date of the current (or last) alert.

    """

    def __init__(self, URL, influxClient):
        """Sets the URL and influxDBClient as speficied in the parameters.
        Also initializes the alert data of the website.

        Args:
            URL (str): URL of the monitored website.
            influxClient (InfluxDBClient): Client for the InfluxDB used to store monitoring data.

        """
        self.URL = URL
        self.influxClient = influxClient
        self.alertData = {
            'alertStatus': False,
            'alertNumber': 0,
            'alertTime': datetime.now()
        }

    def getStats(self, minutes):
        """Retrieves data about the monitored website from the InfluxDB database.
        The data retrieved is only the data recorded during the last {minutes} minutes, minutes 

        Args:
            minutes (int): The number of minutes in the past over which data is retrieved.

        Returns:
            A tuple composed of:
                - a boolean (False if the is no data about the website for the specified timespan, True otherwise)
                - a dictionary containing interesting stats about the website for the specified timeframe:
                    availability (float): Availability of the website.
                    statusCodes (collections.Counter): The counts of the different response codes from requests on the website.
                    avgRT (float): The average response time.
                    minRT (float): The minimum response time.
                    maxRT (float): The maximum response time.
  
        """

        # First, we query the database
        data = self.influxClient.query("SELECT available, status, responseTime FROM website_availability WHERE time > now() - {}m AND host = '{}'".format(minutes, self.URL)).raw
        
        # The raw data from the query is a dictionary object.
        # The interesting data (for us) is associated to the series key 
        if 'series' in data.keys():
            # If there is available data
            # data['series'] is an array whose only relevant element for us is the first
            # This element (data['series'][0]) contains another dictionary
            # In the 'values' key of this dictionary, we can find an array whose first element is the time
            # and whose following elements are the elements we requested, in the order they were requested

            # We create a counter of number of times the site was available or not
            availables = Counter([elt[1] for elt in data['series'][0]['values'] if elt[1] is not None])
            
            # We create an array containing all the (not None) latencies
            responseTimes = [elt[3] for elt in data['series'][0]['values'] if elt[3] is not None]

            # And we create a counter of status codes
            statusCodes = Counter([elt[2] for elt in data['series'][0]['values']])
        else:
            # If there is no data available
            return False, {}

        # We then compute some interesting statistics
        nRT= len(responseTimes)
        minRT = min(responseTimes, default=float('inf'))
        maxRT = max(responseTimes, default=float('inf'))
        try:
            avgRT = sum(responseTimes) / nRT
        except:
            avgRT = float('inf')

        # We define here the availability
        n = sum(availables.values())
        availability = availables[True] / n

        # And we return these stats in a dictionary
        return True, {
                'availability': availability,
                'statusCodes': statusCodes,
                'avgRT': avgRT,
                'minRT': minRT,
                'maxRT': maxRT,
                }
    
    def checkAlert(self):
        """Checks if an availability alert (or recovery) message should be sent, and also stores the notification data in
        the influxDB database.
        The check timeframe is 2 minutes.

        Returns:
            A dictionary composed of:
                - type (string): the type of notification (or None if there is no notification; in that case, the following
                  fields do not exist).
                - URL (string): the website URL.
                - availability (float): the availability of the website at the time of notification.
                - alertTime (datetime.datetime): the time of notification.
                - alertNumber (int): the alert number for the website.
        """
 
        # We first retrieve the website's data on the last 2 minutes
        availables = Counter([elt[1] for elt in self.influxClient.query("SELECT available FROM website_availability WHERE time > now() - 2m AND host = '{}'".format(self.URL)).raw['series'][0]['values']])
        n = sum(availables.values())
        # We compute the site's availability
        availability = availables[True] / n
        currentDate = datetime.utcnow()

        if self.alertData['alertStatus'] and availability >= 0.8:
            # If the website was in alert status but has recovered, we send a recovery signal and store the recovery 
            # in the database
            data = [
                {
                    "measurement": "website_alerts",
                    "tags": {
                        "host": self.URL 
                    },
                    "time": currentDate.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "fields": {
                        "type": "recovery",
                        "availability": availability,
                    }
                }
            ]
            self.alertData['alertStatus'] = False
            self.influxClient.write_points(data)
            return {
                "type": 'recovery',
                "URL": self.URL,
                "availability": availability,
                "alertTime": currentDate,
                "alertNumber": str(self.alertData['alertNumber'])
            }

        elif self.alertData['alertStatus']:
            # If the website was in alert status and still is, we send a downtime signal
            return {
                "type": 'alert',
                "URL": self.URL,
                "availability": availability,
                "alertTime": self.alertData['alertTime'],
                "alertNumber": str(self.alertData['alertNumber'])
            }
        if not(self.alertData['alertStatus']) and availability < 0.8:
            # If the website is now down, we update the alert values and then we send a downtime signal
            # We also write the alert notification in the database
            data = [
                {
                    "measurement": "website_alerts",
                    "tags": {
                        "host": self.URL
                    },
                    "time": currentDate.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "fields": {
                        "type": "alert",
                        "availability": availability,
                    }
                }
            ]
            self.alertData['alertStatus'] = True
            self.alertData['alertNumber'] += 1
            self.alertData['alertTime'] = currentDate
            self.influxClient.write_points(data)
            
            return {
                "type": 'alert',
                "URL": self.URL,
                "availability": availability,
                "alertTime": self.alertData['alertTime'],
                "alertNumber": str(self.alertData['alertNumber'])
            }
        # If there's no problem, we only send that type is None
        return { "type": None }
