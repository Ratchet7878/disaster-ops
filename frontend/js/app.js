// App bootstrap: registers every route (spec section 160's route list)
// and kicks off the hash router.

Router.route('/login', { public: true, render: renderLogin });

Router.route('/volunteer/dashboard', { roles: ['VOLUNTEER', 'SHELTER_MANAGER'], render: renderVolunteerDashboard });
Router.route('/volunteer/report', { roles: ['VOLUNTEER', 'SHELTER_MANAGER'], render: renderVolunteerReport });
Router.route('/volunteer/critical-update', { roles: ['VOLUNTEER', 'SHELTER_MANAGER'], render: renderVolunteerCritical });
Router.route('/volunteer/request', { roles: ['VOLUNTEER', 'SHELTER_MANAGER'], render: renderVolunteerRequest });
Router.route('/volunteer/deliveries', { roles: ['VOLUNTEER', 'SHELTER_MANAGER'], render: renderVolunteerDeliveries });

Router.route('/coordinator/dashboard', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorDashboard });
Router.route('/coordinator/agent', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorAgent });
Router.route('/coordinator/shelters', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorShelters });
Router.route('/coordinator/shelters/:id', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorShelters });
Router.route('/coordinator/needs', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorNeeds });
Router.route('/coordinator/needs/:id', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorNeeds });
Router.route('/coordinator/missions', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorMissions });
Router.route('/coordinator/vehicles', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorVehicles });
Router.route('/coordinator/resources', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorResources });
Router.route('/coordinator/roads', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorRoads });
Router.route('/coordinator/audit', { roles: ['COORDINATOR', 'ADMIN'], render: renderCoordinatorAudit });

Router.renderRoute();
